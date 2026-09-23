"""Tests for login session persistence and remember_me behavior."""
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLoginSession(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.environ['DATA_DIR'] = self.tmpdir

        heavy = [
            'services.twitter_service', 'services.xhs_service',
            'services.wechat_service', 'services.youtube_service',
            'services.webpage_service', 'services.file_manager',
            'services.media_downloader', 'services.config_manager',
            'services.background', 'services.playwright_scraper',
        ]
        self.mocks = {m: MagicMock() for m in heavy}
        self.patcher = patch.dict('sys.modules', self.mocks)
        self.patcher.start()

        import app as flask_app
        self.flask_app = flask_app
        self.app = flask_app.app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.patcher.stop()

    def test_default_session_lifetime_is_365_days(self):
        """Verify default session lifetime is configured to 365 days."""
        self.assertEqual(self.app.permanent_session_lifetime, timedelta(days=365))
        self.assertEqual(self.app.config['PERMANENT_SESSION_LIFETIME'], timedelta(days=365))

    def test_login_with_remember_me_sets_permanent_session(self):
        """Verify checking remember_me sets permanent session without mutating global lifetime."""
        with patch.object(self.flask_app.user_manager, 'authenticate', return_value=True):
            resp = self.client.post('/login', data={
                'username': 'admin',
                'password': 'password',
                'remember_days': '365'
            })
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(self.app.permanent_session_lifetime, timedelta(days=365))

            with self.client.session_transaction() as sess:
                self.assertTrue(sess.get('logged_in'))
                self.assertEqual(sess.get('username'), 'admin')
                self.assertTrue(sess.permanent)

    def test_login_without_remember_me_sets_temporary_session(self):
        """Verify unchecking remember_me sets non-permanent session without altering global lifetime."""
        with patch.object(self.flask_app.user_manager, 'authenticate', return_value=True):
            resp = self.client.post('/login', data={
                'username': 'admin',
                'password': 'password'
            })
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(self.app.permanent_session_lifetime, timedelta(days=365))

            with self.client.session_transaction() as sess:
                self.assertTrue(sess.get('logged_in'))
                self.assertFalse(sess.permanent)

    def test_login_html_defaults_remember_me_to_checked(self):
        """Verify login.html template has remember_me checkbox checked by default."""
        resp = self.client.get('/login')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('id="remember_me"', html)
        self.assertIn('checked', html)


if __name__ == '__main__':
    unittest.main()

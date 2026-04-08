"""Tests for API key authentication in /api/submit."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_test_app():
    """Create a minimal Flask test app with a temp DATA_DIR."""
    tmpdir = tempfile.mkdtemp()
    os.environ['DATA_DIR'] = tmpdir

    heavy = [
        'services.twitter_service', 'services.xhs_service',
        'services.wechat_service', 'services.youtube_service',
        'services.webpage_service', 'services.file_manager',
        'services.media_downloader', 'services.config_manager',
        'services.background', 'services.playwright_scraper',
    ]
    mocks = {m: MagicMock() for m in heavy}
    with patch.dict('sys.modules', mocks):
        import app as flask_app
        flask_app.app.config['TESTING'] = True
        flask_app.init_db()
        return flask_app.app.test_client(), flask_app, tmpdir


class TestCheckApiKey(unittest.TestCase):

    def setUp(self):
        self.client, self.flask_app, self.tmpdir = make_test_app()
        from services.db import set_setting
        set_setting('api_key', '')  # ensure clean state

    def test_no_key_configured_allows_request(self):
        """When no API key is set, any request passes."""
        result = self.flask_app.check_api_key(None)
        self.assertTrue(result)

    def test_correct_bearer_header_passes(self):
        """Authorization: Bearer <key> with correct key passes."""
        from services.db import set_setting
        set_setting('api_key', 'abc123')
        result = self.flask_app.check_api_key('abc123')
        self.assertTrue(result)

    def test_wrong_key_fails(self):
        """Wrong key returns False."""
        from services.db import set_setting
        set_setting('api_key', 'abc123')
        result = self.flask_app.check_api_key('wrongkey')
        self.assertFalse(result)

    def test_empty_provided_key_fails_when_key_set(self):
        """Empty provided key fails when a key is configured."""
        from services.db import set_setting
        set_setting('api_key', 'abc123')
        result = self.flask_app.check_api_key('')
        self.assertFalse(result)


class TestApiSubmitAuth(unittest.TestCase):

    def setUp(self):
        self.client, self.flask_app, self.tmpdir = make_test_app()
        from services.db import set_setting
        set_setting('api_key', '')  # ensure clean state

    def _set_api_key(self, key):
        from services.db import set_setting
        set_setting('api_key', key)

    def test_submit_no_key_configured_no_header(self):
        """No key configured: request without header is accepted (reaches URL validation)."""
        resp = self.client.post('/api/submit',
            json={'url': 'https://x.com/user/status/123'})
        self.assertNotEqual(resp.status_code, 401)

    def test_submit_with_key_configured_no_header_returns_401(self):
        """Key configured: request without any key returns 401."""
        self._set_api_key('mysecretkey')
        resp = self.client.post('/api/submit',
            json={'url': 'https://x.com/user/status/123'})
        self.assertEqual(resp.status_code, 401)
        data = json.loads(resp.data)
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], 'Unauthorized')

    def test_submit_with_correct_bearer_header(self):
        """Correct Authorization: Bearer header passes auth (reaches URL processing)."""
        self._set_api_key('mysecretkey')
        resp = self.client.post('/api/submit',
            json={'url': 'https://x.com/user/status/123'},
            headers={'Authorization': 'Bearer mysecretkey'})
        self.assertNotEqual(resp.status_code, 401)

    def test_submit_with_correct_json_api_key(self):
        """api_key field in JSON body passes auth."""
        self._set_api_key('mysecretkey')
        resp = self.client.post('/api/submit',
            json={'url': 'https://x.com/user/status/123', 'api_key': 'mysecretkey'})
        self.assertNotEqual(resp.status_code, 401)

    def test_submit_with_wrong_bearer_header(self):
        """Wrong Bearer token returns 401."""
        self._set_api_key('mysecretkey')
        resp = self.client.post('/api/submit',
            json={'url': 'https://x.com/user/status/123'},
            headers={'Authorization': 'Bearer wrongkey'})
        self.assertEqual(resp.status_code, 401)


class TestApiKeySettingsEndpoints(unittest.TestCase):

    def setUp(self):
        self.client, self.flask_app, self.tmpdir = make_test_app()
        from services.db import set_setting
        set_setting('api_key', '')  # ensure clean state
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

    def test_get_api_key_no_key(self):
        resp = self.client.get('/api/settings/api-key')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertFalse(data['has_key'])

    def test_generate_api_key(self):
        resp = self.client.post('/api/settings/api-key/generate')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertIn('key', data)
        self.assertEqual(len(data['key']), 64)

    def test_revoke_api_key(self):
        from services.db import set_setting
        set_setting('api_key', 'somekey')
        resp = self.client.delete('/api/settings/api-key')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        from services.db import get_setting
        self.assertEqual(get_setting('api_key', ''), '')


if __name__ == '__main__':
    unittest.main()

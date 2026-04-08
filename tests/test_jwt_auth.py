"""
Tests for JWT token authentication endpoints and Bearer token middleware.
RED phase: all tests should fail before implementation.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import jwt

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_test_app():
    """Create a minimal Flask test app with a temp DATA_DIR."""
    tmpdir = tempfile.mkdtemp()
    os.environ['DATA_DIR'] = tmpdir

    # Write a known secret key
    with open(os.path.join(tmpdir, 'secret_key.txt'), 'w') as f:
        f.write('test-secret-key-for-jwt-tests')

    # Stub out heavy service imports before importing app
    heavy = [
        'services.twitter_service', 'services.xhs_service',
        'services.wechat_service', 'services.youtube_service',
        'services.douyin_service', 'services.weibo_service',
        'services.bilibili_service', 'services.kuaishou_service',
        'services.instagram_service', 'services.zhihu_service',
        'services.pinterest_service', 'services.reddit_service',
        'services.webpage_service', 'services.playwright_scraper',
        'services.background', 'services.db',
        'utils.realtime_logger',
    ]
    mocks = {}
    for mod in heavy:
        m = MagicMock()
        sys.modules[mod] = m
        mocks[mod] = m

    # Provide symbols app.py imports from db and background
    sys.modules['services.db'].get_db_connection = MagicMock()
    sys.modules['services.db'].init_db = MagicMock()
    sys.modules['services.db'].rebuild_fts_index = MagicMock()
    sys.modules['services.db'].generate_unique_slug = MagicMock(return_value='slug')
    sys.modules['services.db'].get_setting = MagicMock(return_value=None)
    sys.modules['services.db'].set_setting = MagicMock()
    sys.modules['services.db'].fts_upsert = MagicMock()
    sys.modules['services.db']._read_full_text = MagicMock(return_value='')
    sys.modules['services.db']._read_title = MagicMock(return_value='')
    sys.modules['services.db'].get_current_time = MagicMock()
    sys.modules['services.db'].format_time_for_db = MagicMock()
    sys.modules['services.db'].parse_time_from_db = MagicMock()
    sys.modules['services.db'].normalize_path_cross_platform = MagicMock()
    sys.modules['services.db'].find_actual_tweet_directory = MagicMock()
    sys.modules['services.background'].processing_queue = MagicMock()
    sys.modules['services.background'].is_processing = MagicMock()
    sys.modules['services.background']._queued_task_ids = set()
    sys.modules['services.background']._queued_task_ids_lock = MagicMock()
    sys.modules['services.background'].processing_thread = MagicMock()
    sys.modules['services.background'].current_task_status = {}
    sys.modules['services.background'].enqueue_task = MagicMock()
    sys.modules['services.background'].init_background = MagicMock()
    sys.modules['services.background'].start_background_thread = MagicMock()
    sys.modules['services.background'].load_pending_tasks = MagicMock()
    sys.modules['utils.realtime_logger'].log_buffer = []
    sys.modules['utils.realtime_logger'].log_lock = MagicMock()
    sys.modules['utils.realtime_logger'].log = MagicMock()
    sys.modules['utils.realtime_logger'].info = MagicMock()
    sys.modules['utils.realtime_logger'].error = MagicMock()
    sys.modules['utils.realtime_logger'].warning = MagicMock()
    sys.modules['utils.realtime_logger'].success = MagicMock()
    sys.modules['utils.realtime_logger'].debug = MagicMock()
    sys.modules['utils.realtime_logger'].get_formatted_logs = MagicMock(return_value=[])
    sys.modules['utils.realtime_logger'].get_logs_after = MagicMock(return_value=[])
    sys.modules['utils.realtime_logger'].get_latest_seq = MagicMock(return_value=0)
    sys.modules['utils.realtime_logger'].format_log_entry = MagicMock()

    import importlib
    import app as flask_app
    importlib.reload(flask_app)

    flask_app.app.config['TESTING'] = True
    flask_app.app.config['DATA_DIR'] = tmpdir
    return flask_app.app, tmpdir, mocks


class TestJWTTokenEndpoint(unittest.TestCase):
    """POST /api/auth/token"""

    def setUp(self):
        self.app, self.tmpdir, self.mocks = make_test_app()
        self.client = self.app.test_client()

        # Patch user_manager on the app module
        import app as flask_app
        self.user_manager_patcher = patch.object(
            flask_app, 'user_manager', autospec=True
        )
        self.mock_user_manager = self.user_manager_patcher.start()

    def tearDown(self):
        self.user_manager_patcher.stop()

    def test_valid_credentials_return_token(self):
        """Valid username+password should return a JWT token."""
        self.mock_user_manager.authenticate.return_value = True

        resp = self.client.post(
            '/api/auth/token',
            json={'username': 'admin', 'password': 'admin'},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('token', data)
        self.assertIsInstance(data['token'], str)
        self.assertGreater(len(data['token']), 20)

    def test_token_contains_username(self):
        """JWT payload should contain the username."""
        self.mock_user_manager.authenticate.return_value = True

        resp = self.client.post(
            '/api/auth/token',
            json={'username': 'admin', 'password': 'admin'},
        )
        data = resp.get_json()
        payload = jwt.decode(
            data['token'],
            self.app.secret_key,
            algorithms=['HS256'],
        )
        self.assertEqual(payload['sub'], 'admin')

    def test_invalid_credentials_return_401(self):
        """Wrong password should return 401."""
        self.mock_user_manager.authenticate.return_value = False

        resp = self.client.post(
            '/api/auth/token',
            json={'username': 'admin', 'password': 'wrong'},
        )
        self.assertEqual(resp.status_code, 401)

    def test_missing_fields_return_400(self):
        """Missing username or password should return 400."""
        resp = self.client.post('/api/auth/token', json={'username': 'admin'})
        self.assertEqual(resp.status_code, 400)

        resp = self.client.post('/api/auth/token', json={'password': 'admin'})
        self.assertEqual(resp.status_code, 400)

    def test_empty_body_return_400(self):
        """Empty body should return 400."""
        resp = self.client.post('/api/auth/token', json={})
        self.assertEqual(resp.status_code, 400)


class TestJWTMeEndpoint(unittest.TestCase):
    """GET /api/auth/me"""

    def setUp(self):
        self.app, self.tmpdir, self.mocks = make_test_app()
        self.client = self.app.test_client()

    def _make_token(self, username='admin', expired=False):
        from datetime import timezone
        import jwt as pyjwt
        from datetime import datetime, timedelta
        exp = datetime.now(timezone.utc) + (
            timedelta(seconds=-1) if expired else timedelta(days=30)
        )
        return pyjwt.encode(
            {'sub': username, 'exp': exp},
            self.app.secret_key,
            algorithm='HS256',
        )

    def test_valid_token_returns_username(self):
        """Valid Bearer token should return 200 with username."""
        token = self._make_token('admin')
        resp = self.client.get(
            '/api/auth/me',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['username'], 'admin')

    def test_missing_token_returns_401(self):
        """No Authorization header should return 401."""
        resp = self.client.get('/api/auth/me')
        self.assertEqual(resp.status_code, 401)

    def test_invalid_token_returns_401(self):
        """Garbage token should return 401."""
        resp = self.client.get(
            '/api/auth/me',
            headers={'Authorization': 'Bearer not.a.valid.token'},
        )
        self.assertEqual(resp.status_code, 401)

    def test_expired_token_returns_401(self):
        """Expired token should return 401."""
        token = self._make_token(expired=True)
        resp = self.client.get(
            '/api/auth/me',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(resp.status_code, 401)


class TestBearerTokenMiddleware(unittest.TestCase):
    """API endpoints should accept Bearer token as an alternative to session auth."""

    def setUp(self):
        self.app, self.tmpdir, self.mocks = make_test_app()
        self.client = self.app.test_client()

    def _make_token(self, username='admin'):
        from datetime import timezone
        import jwt as pyjwt
        from datetime import datetime, timedelta
        return pyjwt.encode(
            {'sub': username, 'exp': datetime.now(timezone.utc) + timedelta(days=30)},
            self.app.secret_key,
            algorithm='HS256',
        )

    def test_api_saved_accepts_bearer_token(self):
        """GET /api/saved should return 200 (not 302/401) when Bearer token is valid."""
        import app as flask_app

        # fetchone() must support dict-style access (sqlite3.Row behaviour)
        count_row = {'count': 0}
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = count_row

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_cursor

        with patch.object(flask_app, 'get_db_connection', return_value=mock_conn):
            token = self._make_token()
            resp = self.client.get(
                '/api/saved',
                headers={'Authorization': f'Bearer {token}'},
            )
        # Should not get a login redirect (302) or auth error (401)
        self.assertNotIn(resp.status_code, [302, 401])

    def test_api_rejects_invalid_bearer_token(self):
        """API endpoints should return 401 for invalid Bearer tokens."""
        resp = self.client.get(
            '/api/saved',
            headers={'Authorization': 'Bearer invalid.token.here'},
        )
        self.assertEqual(resp.status_code, 401)


if __name__ == '__main__':
    unittest.main()

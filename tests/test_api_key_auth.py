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


def _clear_api_keys():
    """Helper to clear the api_keys table."""
    from services.db import get_db_connection
    conn = get_db_connection()
    conn.execute("DELETE FROM api_keys")
    conn.commit()
    conn.close()


def _insert_api_key(name, key):
    """Helper to insert a key into api_keys table."""
    from services.db import get_db_connection
    conn = get_db_connection()
    conn.execute("INSERT INTO api_keys (name, key) VALUES (?, ?)", (name, key))
    conn.commit()
    conn.close()


class TestCheckApiKey(unittest.TestCase):

    def setUp(self):
        self.client, self.flask_app, self.tmpdir = make_test_app()
        _clear_api_keys()

    def test_no_key_configured_allows_request(self):
        """When no API key is set, any request passes."""
        result = self.flask_app.check_api_key(None)
        self.assertTrue(result)

    def test_correct_bearer_header_passes(self):
        """Authorization: Bearer <key> with correct key passes."""
        _insert_api_key('Test', 'abc123')
        result = self.flask_app.check_api_key('abc123')
        self.assertTrue(result)

    def test_wrong_key_fails(self):
        """Wrong key returns False."""
        _insert_api_key('Test', 'abc123')
        result = self.flask_app.check_api_key('wrongkey')
        self.assertFalse(result)

    def test_empty_provided_key_fails_when_key_set(self):
        """Empty provided key fails when a key is configured."""
        _insert_api_key('Test', 'abc123')
        result = self.flask_app.check_api_key('')
        self.assertFalse(result)


class TestApiSubmitAuth(unittest.TestCase):

    def setUp(self):
        self.client, self.flask_app, self.tmpdir = make_test_app()
        _clear_api_keys()

    def _set_api_key(self, key):
        _clear_api_keys()
        if key:
            _insert_api_key('Test', key)

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


class TestMultiApiKeys(unittest.TestCase):

    def setUp(self):
        self.client, self.flask_app, self.tmpdir = make_test_app()

    def test_api_keys_table_exists(self):
        """api_keys table should be created by init_db."""
        from services.db import get_db_connection
        conn = get_db_connection()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='api_keys'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)

    def test_legacy_key_migrated(self):
        """Existing api_key in app_settings is migrated to api_keys table."""
        from services.db import set_setting, get_db_connection, init_db
        set_setting('api_key', 'legacykey123')
        init_db()  # re-run migration
        conn = get_db_connection()
        row = conn.execute("SELECT name, key FROM api_keys WHERE key = 'legacykey123'").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row['name'], 'Default')

    def test_check_api_key_uses_new_table(self):
        """check_api_key matches against api_keys table."""
        from services.db import get_db_connection
        conn = get_db_connection()
        conn.execute("INSERT INTO api_keys (name, key) VALUES ('Test', 'newstylekey')")
        conn.commit()
        conn.close()
        self.assertTrue(self.flask_app.check_api_key('newstylekey'))
        self.assertFalse(self.flask_app.check_api_key('wrongkey'))

    def test_check_api_key_empty_table_allows_all(self):
        """No keys in api_keys table → allow all (backward compat)."""
        _clear_api_keys()
        self.assertTrue(self.flask_app.check_api_key('anything'))
        self.assertTrue(self.flask_app.check_api_key(''))


if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import patch, MagicMock
import subprocess
import os
import time

from utils.ytdlp_helper import (
    is_ytdlp_outdated_error,
    ensure_ytdlp_path,
    upgrade_ytdlp,
    run_ytdlp,
    _UPGRADE_LOCK
)


class TestYtDlpHelper(unittest.TestCase):

    def test_is_ytdlp_outdated_error(self):
        # Should identify 403 Forbidden & outdated version errors
        self.assertTrue(is_ytdlp_outdated_error("WARNING: Your yt-dlp version (2026.03.17) is older than 90 days!"))
        self.assertTrue(is_ytdlp_outdated_error("ERROR: unable to download video data: HTTP Error 403: Forbidden"))
        self.assertTrue(is_ytdlp_outdated_error("HTTP Error 403"))
        self.assertTrue(is_ytdlp_outdated_error("n challenge failed for player"))
        self.assertTrue(is_ytdlp_outdated_error("signature extraction failed"))
        self.assertTrue(is_ytdlp_outdated_error("Sign in to confirm you’re not a bot"))

        # Should return False for unrelated errors
        self.assertFalse(is_ytdlp_outdated_error("Connection refused: 127.0.0.1:8080"))
        self.assertFalse(is_ytdlp_outdated_error("No such file or directory: /tmp/test.mp4"))
        self.assertFalse(is_ytdlp_outdated_error(""))
        self.assertFalse(is_ytdlp_outdated_error(None))

    def test_ensure_ytdlp_path(self):
        with patch.dict(os.environ, {'PATH': '/usr/bin:/bin'}, clear=False):
            ensure_ytdlp_path()
            current_path = os.environ['PATH']
            self.assertIn('/usr/bin', current_path)

    @patch('subprocess.run')
    def test_upgrade_ytdlp_cooldown(self, mock_run):
        # First upgrade: force=True
        mock_run.return_value = MagicMock(returncode=0, stdout='2026.08.19\n', stderr='')
        res = upgrade_ytdlp(force=True)
        self.assertTrue(res)
        self.assertTrue(mock_run.called)

        # Immediate second upgrade without force: should skip due to cooldown
        mock_run.reset_mock()
        res2 = upgrade_ytdlp(force=False)
        self.assertTrue(res2)
        mock_run.assert_not_called()

    @patch('utils.ytdlp_helper.upgrade_ytdlp')
    @patch('subprocess.run')
    def test_run_ytdlp_auto_recovery_on_403(self, mock_subproc_run, mock_upgrade):
        # First call fails with 403 Forbidden, second call succeeds
        fail_proc = MagicMock(returncode=1, stderr='ERROR: unable to download video data: HTTP Error 403: Forbidden', stdout='')
        success_proc = MagicMock(returncode=0, stderr='', stdout='[download] 100%')
        mock_subproc_run.side_effect = [fail_proc, success_proc]
        mock_upgrade.return_value = True

        result = run_ytdlp(['yt-dlp', 'https://youtube.com/watch?v=test'], auto_retry_on_upgrade=True)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(mock_upgrade.called)
        self.assertEqual(mock_subproc_run.call_count, 2)


if __name__ == '__main__':
    unittest.main()

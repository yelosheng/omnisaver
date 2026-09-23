"""Tests for XHS URL extraction, shortlink resolution, and normalization."""
import unittest
from unittest.mock import patch, MagicMock
from services.xhs_service import XHSService


class TestXHSUrlResolution(unittest.TestCase):
    def test_extract_url_from_share_text(self):
        text = (
            "吓一跳，20年A股和美股硬核数据 20年硬核数据｜终于看... "
            "https://xhslink.cn/o/8O1jgGeKJgW "
            "把口令拷走，打开【小红书】查看详情~"
        )
        extracted = XHSService.extract_url_from_share_text(text)
        self.assertEqual(extracted, "https://xhslink.cn/o/8O1jgGeKJgW")

    def test_normalize_discovery_item_url(self):
        url = "https://www.xiaohongshu.com/discovery/item/6ab288e9000000003003f9d1?xsec_token=CBqfvvkL"
        normalized = XHSService.normalize_xhs_url(url)
        self.assertEqual(
            normalized,
            "https://www.xiaohongshu.com/explore/6ab288e9000000003003f9d1?xsec_token=CBqfvvkL"
        )
        self.assertTrue(XHSService.is_valid_xhs_url(normalized))

    def test_normalize_login_redirect_url(self):
        url = (
            "https://www.xiaohongshu.com/login?redirectPath="
            "http%3A%2F%2Fwww.xiaohongshu.com%2Fdiscovery%2Fitem%2F6ab288e9000000003003f9d1%3Fxsec_token%3DCBqfvvkL%253D"
        )
        normalized = XHSService.normalize_xhs_url(url)
        self.assertEqual(
            normalized,
            "https://www.xiaohongshu.com/explore/6ab288e9000000003003f9d1?xsec_token=CBqfvvkL="
        )
        self.assertTrue(XHSService.is_valid_xhs_url(normalized))

    def test_resolve_xhslink_stops_at_valid_note(self):
        """Verify resolve_xhslink captures first 302 location and stops before login redirect."""
        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {
            'Location': 'https://www.xiaohongshu.com/discovery/item/6ab288e9000000003003f9d1?xsec_token=test123'
        }

        with patch('requests.Session.get', return_value=mock_resp):
            resolved = XHSService.resolve_xhslink('https://xhslink.cn/o/8O1jgGeKJgW')
            self.assertEqual(
                resolved,
                'https://www.xiaohongshu.com/discovery/item/6ab288e9000000003003f9d1?xsec_token=test123'
            )
            normalized = XHSService.normalize_xhs_url(resolved)
            self.assertTrue(XHSService.is_valid_xhs_url(normalized))

    def test_resolve_xhslink_handles_login_redirect_fallback(self):
        """Verify resolve_xhslink handles location pointing directly to /login?redirectPath=..."""
        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {
            'Location': 'https://www.xiaohongshu.com/login?redirectPath=http%3A%2F%2Fwww.xiaohongshu.com%2Fdiscovery%2Fitem%2F6ab288e9000000003003f9d1%3Fxsec_token%3Dtest123'
        }

        with patch('requests.Session.get', return_value=mock_resp):
            resolved = XHSService.resolve_xhslink('https://xhslink.cn/o/8O1jgGeKJgW')
            normalized = XHSService.normalize_xhs_url(resolved)
            self.assertEqual(
                normalized,
                'https://www.xiaohongshu.com/explore/6ab288e9000000003003f9d1?xsec_token=test123'
            )
            self.assertTrue(XHSService.is_valid_xhs_url(normalized))

    def test_live_resolution_user_url(self):
        """Live test against the actual URL submitted by the user."""
        raw_url = "https://xhslink.cn/o/8O1jgGeKJgW"
        resolved = XHSService.resolve_xhslink(raw_url)
        normalized = XHSService.normalize_xhs_url(resolved)
        self.assertTrue(XHSService.is_valid_xhs_url(normalized))
        self.assertIn("6ab288e9000000003003f9d1", normalized)
        self.assertIn("explore", normalized)


if __name__ == '__main__':
    unittest.main()

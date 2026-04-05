import unittest

from services.pinterest_service import PinterestService


class TestPinterestService(unittest.TestCase):
    def test_is_valid_pinterest_url(self):
        self.assertTrue(PinterestService.is_valid_pinterest_url('https://www.pinterest.com/pin/99360735500167749/'))
        self.assertTrue(PinterestService.is_valid_pinterest_url('https://pin.it/4qbO3p6JQ'))
        self.assertFalse(PinterestService.is_valid_pinterest_url('https://example.com/post/123'))

    def test_extract_url_from_share_text(self):
        text = '快看这个 Pinterest 分享链接 https://pin.it/4qbO3p6JQ 复制打开即可'
        self.assertEqual(PinterestService.extract_url_from_share_text(text), 'https://pin.it/4qbO3p6JQ')

    def test_extract_direct_pin_url(self):
        text = 'Pin: https://www.pinterest.com/pin/99360735500167749/?utm_source=share'
        self.assertEqual(
            PinterestService.extract_url_from_share_text(text),
            'https://www.pinterest.com/pin/99360735500167749/?utm_source=share',
        )


if __name__ == '__main__':
    unittest.main()

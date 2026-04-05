import unittest

from services.reddit_service import RedditService


class TestRedditService(unittest.TestCase):
    def test_is_valid_reddit_url(self):
        self.assertTrue(RedditService.is_valid_reddit_url('https://www.reddit.com/r/Python/comments/abc123/example_post/'))
        self.assertTrue(RedditService.is_valid_reddit_url('https://redd.it/abc123'))
        self.assertTrue(RedditService.is_valid_reddit_url('https://www.reddit.com/r/Futurology/s/TZA1URgSJi'))
        self.assertFalse(RedditService.is_valid_reddit_url('https://example.com/post/abc123'))

    def test_extract_url_from_share_text(self):
        text = 'Check this out https://www.reddit.com/r/Python/comments/abc123/example_post/?utm_source=share'
        self.assertEqual(
            RedditService.extract_url_from_share_text(text),
            'https://www.reddit.com/r/Python/comments/abc123/example_post/?utm_source=share',
        )
        share_text = 'Reddit share https://www.reddit.com/r/Futurology/s/TZA1URgSJi'
        self.assertEqual(
            RedditService.extract_url_from_share_text(share_text),
            'https://www.reddit.com/r/Futurology/s/TZA1URgSJi',
        )

    def test_extract_post_id(self):
        self.assertEqual(RedditService.extract_post_id('https://www.reddit.com/r/Python/comments/abc123/example_post/'), 'abc123')
        self.assertEqual(RedditService.extract_post_id('https://redd.it/xyz789'), 'xyz789')
        self.assertEqual(RedditService.extract_post_id('https://www.reddit.com/r/Futurology/s/TZA1URgSJi'), '')


if __name__ == '__main__':
    unittest.main()

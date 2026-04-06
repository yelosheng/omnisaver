import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

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

    def test_build_media_candidate_urls_for_reddit_image(self):
        svc = RedditService(base_path='saved_tweets', create_date_folders=False)
        url = 'https://i.redd.it/g3g50yfflhtg1.jpg?width=555&format=pjpg&auto=webp&s=abc'

        candidates = svc._build_media_candidate_urls(url)

        self.assertEqual(candidates[0], url)
        self.assertIn('https://i.redd.it/g3g50yfflhtg1.jpg', candidates)
        self.assertIn('https://preview.redd.it/g3g50yfflhtg1.jpg?width=555&format=pjpg&auto=webp&s=abc', candidates)
        self.assertIn('https://preview.redd.it/g3g50yfflhtg1.jpg', candidates)

    def test_download_file_retries_with_stripped_reddit_query(self):
        svc = RedditService(base_path='saved_tweets', create_date_folders=False)
        svc._sync_rdt_cookies = Mock()

        html_response = Mock()
        html_response.headers = {'Content-Type': 'text/html; charset=utf-8'}
        html_response.raise_for_status = Mock()

        image_response = Mock()
        image_response.headers = {'Content-Type': 'image/jpeg'}
        image_response.raise_for_status = Mock()
        image_response.iter_content = Mock(return_value=[b'jpeg-bytes'])

        svc.media_session.get = Mock(side_effect=[html_response, image_response])

        with TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / 'image.jpg'
            svc._download_file(
                'https://i.redd.it/g3g50yfflhtg1.jpg?width=555&format=pjpg&auto=webp&s=abc',
                dest,
            )
            self.assertEqual(dest.read_bytes(), b'jpeg-bytes')
            self.assertEqual(svc.media_session.get.call_count, 2)


if __name__ == '__main__':
    unittest.main()

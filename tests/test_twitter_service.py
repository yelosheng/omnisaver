import unittest
from unittest.mock import patch, Mock
from datetime import datetime
from services.twitter_service import TwitterService, TwitterScrapingError
from models.tweet import Tweet


class TestTwitterService(unittest.TestCase):
    """TwitterService单元测试"""
    
    def setUp(self):
        """测试前准备"""
        with patch('services.twitter_service.TwitterPlaywrightScraperSync'):
            self.service = TwitterService()
    
    def test_init(self):
        """测试初始化"""
        with patch('services.twitter_service.TwitterPlaywrightScraperSync'):
            service = TwitterService(max_retries=5, timeout=60)
            self.assertEqual(service.max_retries, 5)
            self.assertEqual(service.timeout, 60)
            self.assertTrue(service.use_playwright)
    
    def test_extract_tweet_id_valid(self):
        """测试提取有效的推文ID"""
        url = "https://twitter.com/user/status/1234567890123456789"
        tweet_id = self.service.extract_tweet_id(url)
        self.assertEqual(tweet_id, "1234567890123456789")
    
    def test_extract_tweet_id_invalid(self):
        """测试提取无效的推文ID"""
        invalid_url = "https://facebook.com/post/123"
        with self.assertRaises(ValueError):
            self.service.extract_tweet_id(invalid_url)
    
    @patch('services.twitter_service.requests.get')
    def test_get_tweet_success(self, mock_get):
        """测试成功获取推文"""
        # 模拟API响应
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'data': {
                'id': '1234567890123456789',
                'text': 'Test tweet content',
                'created_at': '2023-01-01T12:00:00.000Z',
                'author_id': 'user123',
                'conversation_id': '1234567890123456789',
                'attachments': {
                    'media_keys': ['media_key_1']
                }
            },
            'includes': {
                'users': [{
                    'id': 'user123',
                    'username': 'testuser',
                    'name': 'Test User'
                }],
                'media': [{
                    'media_key': 'media_key_1',
                    'type': 'photo',
                    'url': 'https://example.com/image.jpg'
                }]
            }
        }
        mock_get.return_value = mock_response
        
        tweet = self.service.get_tweet('1234567890123456789')
        
        self.assertIsInstance(tweet, Tweet)
        self.assertEqual(tweet.id, '1234567890123456789')
        self.assertEqual(tweet.text, 'Test tweet content')
        self.assertEqual(tweet.author_username, 'testuser')
        self.assertEqual(tweet.author_name, 'Test User')
        self.assertEqual(len(tweet.media_urls), 1)
        self.assertEqual(tweet.media_urls[0], 'https://example.com/image.jpg')
        self.assertEqual(tweet.media_types[0], 'photo')
    
    @patch('services.twitter_service.requests.get')
    def test_get_tweet_not_found(self, mock_get):
        """测试推文不存在"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response
        
        with self.assertRaises(TwitterScrapingError) as context:
            self.service.get_tweet('1234567890123456789')
        
        self.assertIn("Tweet not found", str(context.exception))
    
    @patch('services.twitter_service.requests.get')
    def test_get_tweet_unauthorized(self, mock_get):
        """测试未授权访问"""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response
        
        with self.assertRaises(TwitterScrapingError) as context:
            self.service.get_tweet('1234567890123456789')
        
        self.assertIn("Unauthorized", str(context.exception))
    
    @patch('services.twitter_service.requests.get')
    @patch('services.twitter_service.time.sleep')  # 模拟sleep以加速测试
    def test_get_tweet_rate_limit_retry(self, mock_sleep, mock_get):
        """测试速率限制重试"""
        # 第一次请求返回429，第二次请求成功
        mock_responses = [Mock(), Mock()]
        mock_responses[0].status_code = 429
        mock_responses[1].status_code = 200
        mock_responses[1].json.return_value = {
            'data': {
                'id': '1234567890123456789',
                'text': 'Test tweet',
                'created_at': '2023-01-01T12:00:00.000Z',
                'author_id': 'user123',
                'conversation_id': '1234567890123456789'
            },
            'includes': {
                'users': [{
                    'id': 'user123',
                    'username': 'testuser',
                    'name': 'Test User'
                }]
            }
        }
        mock_get.side_effect = mock_responses
        
        tweet = self.service.get_tweet('1234567890123456789')
        
        self.assertIsInstance(tweet, Tweet)
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()
    
    def test_get_tweet_invalid_id(self):
        """测试无效的推文ID"""
        with self.assertRaises(ValueError):
            self.service.get_tweet('invalid_id')
        
        with self.assertRaises(ValueError):
            self.service.get_tweet('')
    
    @patch.object(TwitterService, 'get_tweet')
    def test_get_tweet_by_url(self, mock_get_tweet):
        """测试通过URL获取推文"""
        mock_tweet = Tweet(
            id='1234567890123456789',
            text='Test tweet',
            author_username='testuser',
            author_name='Test User',
            created_at=datetime.now(),
            media_urls=[],
            media_types=[],
            reply_to=None,
            conversation_id='1234567890123456789'
        )
        mock_get_tweet.return_value = mock_tweet
        
        url = "https://twitter.com/user/status/1234567890123456789"
        tweet = self.service.get_tweet_by_url(url)
        
        self.assertEqual(tweet, mock_tweet)
        mock_get_tweet.assert_called_once_with('1234567890123456789')
    
    def test_parse_tweet_data_minimal(self):
        """测试解析最小推文数据"""
        tweet_data = {
            'id': '123',
            'text': 'Hello world',
            'created_at': '2023-01-01T12:00:00.000Z',
            'author_id': 'user123',
            'conversation_id': '123'
        }
        
        tweet = self.service._parse_tweet_data(tweet_data)
        
        self.assertEqual(tweet.id, '123')
        self.assertEqual(tweet.text, 'Hello world')
        self.assertEqual(tweet.author_username, '')  # 没有includes数据
        self.assertEqual(tweet.author_name, '')
        self.assertEqual(len(tweet.media_urls), 0)
    
    def test_parse_tweet_data_with_video(self):
        """测试解析包含视频的推文数据"""
        tweet_data = {
            'id': '123',
            'text': 'Video tweet',
            'created_at': '2023-01-01T12:00:00.000Z',
            'author_id': 'user123',
            'conversation_id': '123',
            'attachments': {
                'media_keys': ['video_key_1']
            }
        }
        
        includes = {
            'users': [{
                'id': 'user123',
                'username': 'videouser',
                'name': 'Video User'
            }],
            'media': [{
                'media_key': 'video_key_1',
                'type': 'video',
                'variants': [
                    {
                        'content_type': 'video/mp4',
                        'bit_rate': 832000,
                        'url': 'https://example.com/video_low.mp4'
                    },
                    {
                        'content_type': 'video/mp4',
                        'bit_rate': 2176000,
                        'url': 'https://example.com/video_high.mp4'
                    }
                ]
            }]
        }
        
        tweet = self.service._parse_tweet_data(tweet_data, includes)
        
        self.assertEqual(tweet.author_username, 'videouser')
        self.assertEqual(len(tweet.media_urls), 1)
        self.assertEqual(tweet.media_urls[0], 'https://example.com/video_high.mp4')  # 选择高质量版本
        self.assertEqual(tweet.media_types[0], 'video')
    
    @patch.object(TwitterService, 'get_tweet')
    @patch.object(TwitterService, '_get_conversation_tweets')
    def test_get_thread(self, mock_get_conversation, mock_get_tweet):
        """测试获取推文串"""
        # 模拟主推文
        main_tweet = Tweet(
            id='123',
            text='Thread 1/3',
            author_username='testuser',
            author_name='Test User',
            created_at=datetime.now(),
            media_urls=[],
            media_types=[],
            reply_to=None,
            conversation_id='123'
        )
        mock_get_tweet.return_value = main_tweet
        
        # 模拟推文串
        thread_tweets = [
            main_tweet,
            Tweet(
                id='124',
                text='Thread 2/3',
                author_username='testuser',
                author_name='Test User',
                created_at=datetime.now(),
                media_urls=[],
                media_types=[],
                reply_to='123',
                conversation_id='123'
            )
        ]
        mock_get_conversation.return_value = thread_tweets
        
        result = self.service.get_thread('123')
        
        self.assertEqual(len(result), 2)
        mock_get_tweet.assert_called_once_with('123')
        mock_get_conversation.assert_called_once_with('123')
    
    @patch.object(TwitterService, 'get_thread')
    def test_get_thread_by_url(self, mock_get_thread):
        """测试通过URL获取推文串"""
        mock_tweets = [Tweet(
            id='123',
            text='Test thread',
            author_username='testuser',
            author_name='Test User',
            created_at=datetime.now(),
            media_urls=[],
            media_types=[],
            reply_to=None,
            conversation_id='123'
        )]
        mock_get_thread.return_value = mock_tweets
        
        url = "https://twitter.com/user/status/123"
        result = self.service.get_thread_by_url(url)
        
        self.assertEqual(result, mock_tweets)
        mock_get_thread.assert_called_once_with('123')


if __name__ == '__main__':
    unittest.main()
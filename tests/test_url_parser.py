import unittest
from utils.url_parser import TwitterURLParser


class TestTwitterURLParser(unittest.TestCase):
    """TwitterURLParser单元测试"""
    
    def setUp(self):
        """测试前准备"""
        self.valid_urls = [
            "https://twitter.com/elonmusk/status/1234567890123456789",
            "https://x.com/elonmusk/status/1234567890123456789",
            "https://mobile.twitter.com/elonmusk/status/1234567890123456789",
            "https://m.twitter.com/elonmusk/status/1234567890123456789",
            "http://twitter.com/user/status/1234567890123456789",
            "https://www.twitter.com/user/status/1234567890123456789",
            "https://www.x.com/user/status/1234567890123456789",
        ]
        
        self.invalid_urls = [
            "https://facebook.com/post/123",
            "https://twitter.com/elonmusk",
            "https://twitter.com/elonmusk/status/",
            "https://twitter.com/elonmusk/status/abc",
            "https://twitter.com/elonmusk/status/123",  # 太短
            "not_a_url",
            "",
            None,
        ]
        
        self.expected_tweet_id = "1234567890123456789"
    
    def test_extract_tweet_id_valid_urls(self):
        """测试从有效URL提取推文ID"""
        for url in self.valid_urls:
            with self.subTest(url=url):
                tweet_id = TwitterURLParser.extract_tweet_id(url)
                self.assertEqual(tweet_id, self.expected_tweet_id)
    
    def test_extract_tweet_id_invalid_urls(self):
        """测试从无效URL提取推文ID"""
        for url in self.invalid_urls:
            with self.subTest(url=url):
                tweet_id = TwitterURLParser.extract_tweet_id(url)
                self.assertIsNone(tweet_id)
    
    def test_extract_tweet_id_with_parameters(self):
        """测试带参数的URL"""
        url_with_params = "https://twitter.com/elonmusk/status/1234567890123456789?s=20&t=abc123"
        tweet_id = TwitterURLParser.extract_tweet_id(url_with_params)
        self.assertEqual(tweet_id, self.expected_tweet_id)
    
    def test_extract_tweet_id_with_fragment(self):
        """测试带片段的URL"""
        url_with_fragment = "https://twitter.com/elonmusk/status/1234567890123456789#reply"
        tweet_id = TwitterURLParser.extract_tweet_id(url_with_fragment)
        self.assertEqual(tweet_id, self.expected_tweet_id)
    
    def test_is_valid_twitter_url(self):
        """测试URL有效性验证"""
        for url in self.valid_urls:
            with self.subTest(url=url):
                self.assertTrue(TwitterURLParser.is_valid_twitter_url(url))
        
        for url in self.invalid_urls:
            with self.subTest(url=url):
                self.assertFalse(TwitterURLParser.is_valid_twitter_url(url))
    
    def test_normalize_url(self):
        """测试URL标准化"""
        for url in self.valid_urls:
            with self.subTest(url=url):
                normalized = TwitterURLParser.normalize_url(url)
                expected = f"https://twitter.com/i/status/{self.expected_tweet_id}"
                self.assertEqual(normalized, expected)
    
    def test_normalize_url_invalid(self):
        """测试无效URL的标准化"""
        for url in self.invalid_urls:
            with self.subTest(url=url):
                normalized = TwitterURLParser.normalize_url(url)
                self.assertIsNone(normalized)
    
    def test_is_valid_tweet_id(self):
        """测试推文ID验证"""
        valid_ids = [
            "1234567890123456789",  # 19位
            "1234567890",           # 10位
            "12345678901234567890", # 20位
        ]
        
        invalid_ids = [
            "123456789",            # 9位，太短
            "123456789012345678901", # 21位，太长
            "abc123",               # 包含字母
            "",                     # 空字符串
            "12345abc67890",        # 包含字母
        ]
        
        for tweet_id in valid_ids:
            with self.subTest(tweet_id=tweet_id):
                self.assertTrue(TwitterURLParser._is_valid_tweet_id(tweet_id))
        
        for tweet_id in invalid_ids:
            with self.subTest(tweet_id=tweet_id):
                self.assertFalse(TwitterURLParser._is_valid_tweet_id(tweet_id))
    
    def test_get_supported_formats(self):
        """测试获取支持的格式"""
        formats = TwitterURLParser.get_supported_formats()
        self.assertIsInstance(formats, list)
        self.assertTrue(len(formats) > 0)
        for format_example in formats:
            self.assertIsInstance(format_example, str)
            self.assertTrue(format_example.startswith('http'))
    
    def test_case_insensitive_matching(self):
        """测试大小写不敏感匹配"""
        urls = [
            "HTTPS://TWITTER.COM/USER/STATUS/1234567890123456789",
            "https://Twitter.Com/user/status/1234567890123456789",
            "HTTPS://X.COM/USER/STATUS/1234567890123456789",
        ]
        
        for url in urls:
            with self.subTest(url=url):
                tweet_id = TwitterURLParser.extract_tweet_id(url)
                self.assertEqual(tweet_id, self.expected_tweet_id)
    
    def test_whitespace_handling(self):
        """测试空白字符处理"""
        url_with_spaces = "  https://twitter.com/user/status/1234567890123456789  "
        tweet_id = TwitterURLParser.extract_tweet_id(url_with_spaces)
        self.assertEqual(tweet_id, self.expected_tweet_id)


if __name__ == '__main__':
    unittest.main()
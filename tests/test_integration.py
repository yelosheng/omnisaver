import unittest
import os
import tempfile
import shutil
from unittest.mock import patch, Mock
from datetime import datetime
from main import main, validate_url, parse_arguments
from services.config_manager import ConfigManager
from services.twitter_service import TwitterService
from services.media_downloader import MediaDownloader
from services.file_manager import FileManager
from models.tweet import Tweet
from models.media_file import MediaFile


class TestIntegration(unittest.TestCase):
    """集成测试"""
    
    def setUp(self):
        """测试前准备"""
        self.test_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.test_dir, 'test_config.ini')
        
        # 创建测试配置文件
        config_content = """[twitter]
bearer_token = test_token

[storage]
base_path = {test_dir}
create_date_folders = true

[download]
max_retries = 1
timeout_seconds = 5
""".format(test_dir=self.test_dir)
        
        with open(self.config_file, 'w') as f:
            f.write(config_content)
    
    def tearDown(self):
        """测试后清理"""
        shutil.rmtree(self.test_dir)
    
    def test_validate_url(self):
        """测试URL验证"""
        valid_urls = [
            "https://twitter.com/user/status/1234567890123456789",
            "https://x.com/user/status/1234567890123456789"
        ]
        
        invalid_urls = [
            "https://facebook.com/post/123",
            "invalid_url",
            ""
        ]
        
        for url in valid_urls:
            self.assertTrue(validate_url(url))
        
        for url in invalid_urls:
            self.assertFalse(validate_url(url))
    
    def test_parse_arguments(self):
        """测试命令行参数解析"""
        # 测试基本参数
        with patch('sys.argv', ['main.py', 'https://twitter.com/user/status/123']):
            args = parse_arguments()
            self.assertEqual(args.url, 'https://twitter.com/user/status/123')
            self.assertFalse(args.no_media)
            self.assertFalse(args.thread_only)
            self.assertEqual(args.config, 'config.ini')
        
        # 测试所有参数
        with patch('sys.argv', [
            'main.py', 
            'https://twitter.com/user/status/123',
            '--no-media',
            '--thread-only',
            '--config', 'custom.ini',
            '--output', '/custom/path',
            '--verbose'
        ]):
            args = parse_arguments()
            self.assertTrue(args.no_media)
            self.assertTrue(args.thread_only)
            self.assertEqual(args.config, 'custom.ini')
            self.assertEqual(args.output, '/custom/path')
            self.assertTrue(args.verbose)
    
    @patch.dict(os.environ, {'TWITTER_BEARER_TOKEN': 'test_token'})
    def test_config_integration(self):
        """测试配置管理集成"""
        config_manager = ConfigManager(self.config_file)
        
        # 测试配置加载
        config = config_manager.load_config()
        self.assertEqual(config['bearer_token'], 'test_token')
        self.assertEqual(config['save_path'], self.test_dir)
        self.assertTrue(config['create_date_folders'])
        self.assertEqual(config['max_retries'], 1)
        self.assertEqual(config['timeout_seconds'], 5)
        
        # 测试配置验证
        self.assertTrue(config_manager.validate_config())
    
    @patch.object(TwitterService, '_validate_token')
    @patch.object(TwitterService, '_make_request')
    def test_twitter_service_integration(self, mock_request, mock_validate):
        """测试Twitter服务集成"""
        # 模拟API响应
        mock_request.return_value = {
            'data': {
                'id': '1234567890123456789',
                'text': 'Test tweet content',
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
        
        service = TwitterService()
        tweet = service.get_tweet('1234567890123456789')
        
        self.assertIsInstance(tweet, Tweet)
        self.assertEqual(tweet.id, '1234567890123456789')
        self.assertEqual(tweet.text, 'Test tweet content')
        self.assertEqual(tweet.author_username, 'testuser')
    
    @patch('services.media_downloader.requests.head')
    @patch('services.media_downloader.requests.get')
    @patch('builtins.open')
    @patch('os.path.exists')
    @patch('os.path.getsize')
    def test_media_downloader_integration(self, mock_getsize, mock_exists, 
                                        mock_open, mock_get, mock_head):
        """测试媒体下载器集成"""
        # 模拟文件不存在
        mock_exists.return_value = False
        mock_getsize.return_value = 0
        
        # 模拟HTTP响应
        mock_head.return_value = Mock(headers={'content-length': '1024'})
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.iter_content.return_value = [b'test_data']
        mock_get.return_value = mock_response
        
        # 模拟文件写入成功
        def exists_side_effect(path):
            return path.endswith('.jpg')
        mock_exists.side_effect = exists_side_effect
        mock_getsize.return_value = 100
        
        downloader = MediaDownloader(max_retries=1, timeout=5)
        urls = ['https://example.com/image.jpg']
        
        result = downloader.download_images(urls, self.test_dir)
        
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], MediaFile)
    
    def test_file_manager_integration(self):
        """测试文件管理器集成"""
        file_manager = FileManager(base_path=self.test_dir, create_date_folders=True)
        
        # 创建测试推文
        tweet = Tweet(
            id="1234567890123456789",
            text="Test tweet",
            author_username="testuser",
            author_name="Test User",
            created_at=datetime(2023, 1, 1, 12, 0, 0),
            media_urls=[],
            media_types=[],
            reply_to=None,
            conversation_id="1234567890123456789"
        )
        
        # 创建保存目录
        save_dir = file_manager.create_save_directory(tweet.id, tweet.created_at)
        self.assertTrue(os.path.exists(save_dir))
        self.assertTrue(save_dir.endswith("2023-01-01_1234567890123456789"))
        
        # 保存推文内容
        file_manager.save_tweet_content(tweet, save_dir)
        content_file = file_manager.get_content_file_path(save_dir)
        self.assertTrue(os.path.exists(content_file))
        
        # 保存元数据
        file_manager.save_metadata([tweet], save_dir)
        metadata_file = file_manager.get_metadata_file_path(save_dir)
        self.assertTrue(os.path.exists(metadata_file))
        
        # 获取摘要
        summary = file_manager.get_save_summary(save_dir, [tweet])
        self.assertEqual(summary['tweet_count'], 1)
        self.assertFalse(summary['is_thread'])
    
    @patch('sys.argv', ['main.py', 'https://twitter.com/user/status/1234567890123456789'])
    @patch.object(TwitterService, '_validate_token')
    @patch.object(TwitterService, '_make_request')
    @patch.object(MediaDownloader, 'download_images')
    @patch.object(MediaDownloader, 'download_videos')
    def test_main_function_single_tweet(self, mock_download_videos, mock_download_images, 
                                      mock_request, mock_validate):
        """测试主函数 - 单个推文"""
        # 设置环境变量
        with patch.dict(os.environ, {'TWITTER_BEARER_TOKEN': 'test_token'}):
            # 模拟API响应
            mock_request.return_value = {
                'data': {
                    'id': '1234567890123456789',
                    'text': 'Test tweet content',
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
            
            # 模拟媒体下载
            mock_download_images.return_value = []
            mock_download_videos.return_value = []
            
            # 使用自定义配置文件
            with patch('sys.argv', [
                'main.py', 
                'https://twitter.com/user/status/1234567890123456789',
                '--config', self.config_file,
                '--output', self.test_dir
            ]):
                # 运行主函数
                try:
                    main()
                except SystemExit as e:
                    # 正常退出
                    self.assertEqual(e.code, None or 0)
                
                # 验证文件是否创建
                # 查找创建的目录
                created_dirs = [d for d in os.listdir(self.test_dir) 
                              if os.path.isdir(os.path.join(self.test_dir, d)) and 
                              '1234567890123456789' in d]
                
                self.assertTrue(len(created_dirs) > 0)
                
                save_dir = os.path.join(self.test_dir, created_dirs[0])
                content_file = os.path.join(save_dir, 'content.txt')
                metadata_file = os.path.join(save_dir, 'metadata.json')
                
                self.assertTrue(os.path.exists(content_file))
                self.assertTrue(os.path.exists(metadata_file))
    
    @patch('sys.argv', ['main.py', 'invalid_url'])
    def test_main_function_invalid_url(self):
        """测试主函数 - 无效URL"""
        with self.assertRaises(SystemExit) as cm:
            main()
        
        self.assertEqual(cm.exception.code, 1)
    
    def test_end_to_end_workflow(self):
        """测试端到端工作流程"""
        # 这个测试模拟完整的工作流程，但使用模拟数据
        
        # 1. 配置管理
        with patch.dict(os.environ, {'TWITTER_BEARER_TOKEN': 'test_token'}):
            config_manager = ConfigManager(self.config_file)
            config = config_manager.load_config()
            self.assertTrue(config_manager.validate_config())
        
        # 2. Twitter服务
        with patch.object(TwitterService, '_validate_token'), \
             patch.object(TwitterService, '_make_request') as mock_request:
            
            mock_request.return_value = {
                'data': {
                    'id': '1234567890123456789',
                    'text': 'End-to-end test tweet',
                    'created_at': '2023-01-01T12:00:00.000Z',
                    'author_id': 'user123',
                    'conversation_id': '1234567890123456789',
                    'attachments': {'media_keys': ['media1']}
                },
                'includes': {
                    'users': [{
                        'id': 'user123',
                        'username': 'testuser',
                        'name': 'Test User'
                    }],
                    'media': [{
                        'media_key': 'media1',
                        'type': 'photo',
                        'url': 'https://example.com/image.jpg'
                    }]
                }
            }
            
            twitter_service = TwitterService()
            tweet = twitter_service.get_tweet('1234567890123456789')
        
        # 3. 媒体下载
        with patch.object(MediaDownloader, '_download_file', return_value=True):
            media_downloader = MediaDownloader()
            media_files = media_downloader.download_images(tweet.media_urls, self.test_dir)
        
        # 4. 文件管理
        file_manager = FileManager(base_path=self.test_dir)
        save_dir = file_manager.create_save_directory(tweet.id, tweet.created_at)
        
        file_manager.save_tweet_content(tweet, save_dir, media_files)
        file_manager.save_metadata([tweet], save_dir, media_files)
        
        # 5. 验证结果
        summary = file_manager.get_save_summary(save_dir, [tweet], media_files)
        
        self.assertEqual(summary['tweet_count'], 1)
        self.assertFalse(summary['is_thread'])
        self.assertTrue(os.path.exists(save_dir))
        self.assertTrue(os.path.exists(file_manager.get_content_file_path(save_dir)))
        self.assertTrue(os.path.exists(file_manager.get_metadata_file_path(save_dir)))


if __name__ == '__main__':
    unittest.main()
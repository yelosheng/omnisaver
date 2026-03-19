import unittest
import os
import json
import tempfile
import shutil
from datetime import datetime
from services.file_manager import FileManager, FileManagerError
from models.tweet import Tweet
from models.media_file import MediaFile


class TestFileManager(unittest.TestCase):
    """FileManager单元测试"""
    
    def setUp(self):
        """测试前准备"""
        self.test_dir = tempfile.mkdtemp()
        self.file_manager = FileManager(base_path=self.test_dir, create_date_folders=True)
        
        # 创建测试推文
        self.test_tweet = Tweet(
            id="1234567890123456789",
            text="这是一条测试推文",
            author_username="testuser",
            author_name="测试用户",
            created_at=datetime(2023, 1, 1, 12, 0, 0),
            media_urls=["https://example.com/image.jpg"],
            media_types=["photo"],
            reply_to=None,
            conversation_id="1234567890123456789"
        )
        
        # 创建测试媒体文件
        self.test_media = MediaFile(
            url="https://example.com/image.jpg",
            local_path=os.path.join(self.test_dir, "images", "image_01.jpg"),
            media_type="photo",
            filename="image_01.jpg"
        )
        
    def tearDown(self):
        """测试后清理"""
        shutil.rmtree(self.test_dir)
    
    def test_init(self):
        """测试初始化"""
        # 测试默认参数
        fm1 = FileManager()
        self.assertEqual(str(fm1.base_path), "/mnt/nas/saved_tweets")
        self.assertTrue(fm1.create_date_folders)
        
        # 测试自定义参数
        fm2 = FileManager(base_path="/custom/path", create_date_folders=False)
        self.assertEqual(str(fm2.base_path), "/custom/path")
        self.assertFalse(fm2.create_date_folders)
    
    def test_create_save_directory_with_date(self):
        """测试创建带日期的保存目录"""
        tweet_date = datetime(2023, 5, 15, 10, 30, 0)
        save_dir = self.file_manager.create_save_directory("123456789", tweet_date)
        
        expected_dir_name = "2023-05-15_123456789"
        self.assertTrue(save_dir.endswith(expected_dir_name))
        self.assertTrue(os.path.exists(save_dir))
    
    def test_create_save_directory_without_date(self):
        """测试创建不带日期的保存目录"""
        fm = FileManager(base_path=self.test_dir, create_date_folders=False)
        save_dir = fm.create_save_directory("123456789")
        
        self.assertTrue(save_dir.endswith("123456789"))
        self.assertTrue(os.path.exists(save_dir))
    
    def test_create_save_directory_current_date(self):
        """测试使用当前日期创建目录"""
        save_dir = self.file_manager.create_save_directory("123456789")
        
        today = datetime.now().strftime("%Y-%m-%d")
        expected_dir_name = f"{today}_123456789"
        self.assertTrue(save_dir.endswith(expected_dir_name))
        self.assertTrue(os.path.exists(save_dir))
    
    def test_get_file_paths(self):
        """测试获取文件路径"""
        save_dir = "/test/dir"
        
        content_path = self.file_manager.get_content_file_path(save_dir)
        metadata_path = self.file_manager.get_metadata_file_path(save_dir)
        
        self.assertEqual(content_path, "/test/dir/content.txt")
        self.assertEqual(metadata_path, "/test/dir/metadata.json")
    
    def test_save_tweet_content(self):
        """测试保存单个推文内容"""
        save_dir = self.file_manager.create_save_directory(self.test_tweet.id, self.test_tweet.created_at)
        
        self.file_manager.save_tweet_content(self.test_tweet, save_dir, [self.test_media])
        
        content_file = self.file_manager.get_content_file_path(save_dir)
        self.assertTrue(os.path.exists(content_file))
        
        # 检查文件内容
        with open(content_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn(self.test_tweet.id, content)
            self.assertIn(self.test_tweet.text, content)
            self.assertIn(self.test_tweet.author_name, content)
            self.assertIn(self.test_tweet.author_username, content)
            self.assertIn("媒体文件", content)
            self.assertIn(self.test_media.filename, content)
    
    def test_save_thread_content(self):
        """测试保存推文串内容"""
        # 创建推文串
        tweet2 = Tweet(
            id="1234567890123456790",
            text="这是推文串的第二条",
            author_username="testuser",
            author_name="测试用户",
            created_at=datetime(2023, 1, 1, 12, 1, 0),
            media_urls=[],
            media_types=[],
            reply_to="1234567890123456789",
            conversation_id="1234567890123456789"
        )
        
        tweets = [self.test_tweet, tweet2]
        save_dir = self.file_manager.create_save_directory(self.test_tweet.id, self.test_tweet.created_at)
        
        self.file_manager.save_thread_content(tweets, save_dir, [self.test_media])
        
        content_file = self.file_manager.get_content_file_path(save_dir)
        self.assertTrue(os.path.exists(content_file))
        
        # 检查文件内容
        with open(content_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn("推文串", content)
            self.assertIn("共 2 条推文", content)
            self.assertIn("推文 1/2", content)
            self.assertIn("推文 2/2", content)
            self.assertIn(self.test_tweet.text, content)
            self.assertIn(tweet2.text, content)
    
    def test_save_thread_content_empty(self):
        """测试保存空推文串"""
        save_dir = self.file_manager.create_save_directory("123")
        
        with self.assertRaises(FileManagerError):
            self.file_manager.save_thread_content([], save_dir)
    
    def test_save_metadata(self):
        """测试保存元数据"""
        save_dir = self.file_manager.create_save_directory(self.test_tweet.id, self.test_tweet.created_at)
        
        self.file_manager.save_metadata([self.test_tweet], save_dir, [self.test_media])
        
        metadata_file = self.file_manager.get_metadata_file_path(save_dir)
        self.assertTrue(os.path.exists(metadata_file))
        
        # 检查元数据内容
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
            
            self.assertEqual(metadata["tweet_count"], 1)
            self.assertFalse(metadata["is_thread"])
            self.assertEqual(len(metadata["tweets"]), 1)
            self.assertEqual(len(metadata["media_files"]), 1)
            
            tweet_data = metadata["tweets"][0]
            self.assertEqual(tweet_data["id"], self.test_tweet.id)
            self.assertEqual(tweet_data["text"], self.test_tweet.text)
            self.assertEqual(tweet_data["author_username"], self.test_tweet.author_username)
            
            media_data = metadata["media_files"][0]
            self.assertEqual(media_data["filename"], self.test_media.filename)
            self.assertEqual(media_data["media_type"], self.test_media.media_type)
    
    def test_save_metadata_thread(self):
        """测试保存推文串元数据"""
        tweet2 = Tweet(
            id="1234567890123456790",
            text="第二条推文",
            author_username="testuser",
            author_name="测试用户",
            created_at=datetime(2023, 1, 1, 12, 1, 0),
            media_urls=[],
            media_types=[],
            reply_to="1234567890123456789",
            conversation_id="1234567890123456789"
        )
        
        tweets = [self.test_tweet, tweet2]
        save_dir = self.file_manager.create_save_directory(self.test_tweet.id)
        
        self.file_manager.save_metadata(tweets, save_dir)
        
        metadata_file = self.file_manager.get_metadata_file_path(save_dir)
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
            
            self.assertEqual(metadata["tweet_count"], 2)
            self.assertTrue(metadata["is_thread"])
            self.assertEqual(len(metadata["tweets"]), 2)
    
    def test_get_save_summary(self):
        """测试获取保存摘要"""
        save_dir = self.file_manager.create_save_directory(self.test_tweet.id)
        
        # 创建文件
        self.file_manager.save_tweet_content(self.test_tweet, save_dir, [self.test_media])
        self.file_manager.save_metadata([self.test_tweet], save_dir, [self.test_media])
        
        summary = self.file_manager.get_save_summary(save_dir, [self.test_tweet], [self.test_media])
        
        self.assertEqual(summary["tweet_count"], 1)
        self.assertFalse(summary["is_thread"])
        self.assertEqual(summary["media_count"], 1)
        self.assertEqual(summary["image_count"], 1)
        self.assertEqual(summary["video_count"], 0)
        self.assertIn("content.txt", summary["files_created"])
        self.assertIn("metadata.json", summary["files_created"])
    
    def test_get_save_summary_thread(self):
        """测试获取推文串保存摘要"""
        tweet2 = Tweet(
            id="1234567890123456790",
            text="第二条推文",
            author_username="testuser",
            author_name="测试用户",
            created_at=datetime(2023, 1, 1, 12, 1, 0),
            media_urls=["https://example.com/video.mp4"],
            media_types=["video"],
            reply_to="1234567890123456789",
            conversation_id="1234567890123456789"
        )
        
        video_media = MediaFile(
            url="https://example.com/video.mp4",
            local_path=os.path.join(self.test_dir, "videos", "video_01.mp4"),
            media_type="video",
            filename="video_01.mp4"
        )
        
        tweets = [self.test_tweet, tweet2]
        media_files = [self.test_media, video_media]
        save_dir = self.file_manager.create_save_directory(self.test_tweet.id)
        
        summary = self.file_manager.get_save_summary(save_dir, tweets, media_files)
        
        self.assertEqual(summary["tweet_count"], 2)
        self.assertTrue(summary["is_thread"])
        self.assertEqual(summary["media_count"], 2)
        self.assertEqual(summary["image_count"], 1)
        self.assertEqual(summary["video_count"], 1)
    
    def test_cleanup_empty_directories(self):
        """测试清理空目录"""
        # 创建一些目录
        empty_dir = os.path.join(self.test_dir, "empty")
        non_empty_dir = os.path.join(self.test_dir, "non_empty")
        
        os.makedirs(empty_dir)
        os.makedirs(non_empty_dir)
        
        # 在non_empty_dir中创建一个文件
        with open(os.path.join(non_empty_dir, "test.txt"), 'w') as f:
            f.write("test")
        
        # 清理空目录
        self.file_manager.cleanup_empty_directories()
        
        # 空目录应该被删除，非空目录应该保留
        self.assertFalse(os.path.exists(empty_dir))
        self.assertTrue(os.path.exists(non_empty_dir))


if __name__ == '__main__':
    unittest.main()
import unittest
import os
import tempfile
import shutil
from unittest.mock import patch, Mock, mock_open
from services.media_downloader import MediaDownloader, MediaDownloadError
from models.media_file import MediaFile


class TestMediaDownloader(unittest.TestCase):
    """MediaDownloader单元测试"""
    
    def setUp(self):
        """测试前准备"""
        self.test_dir = tempfile.mkdtemp()
        self.downloader = MediaDownloader(max_retries=1, timeout=5)
        
    def tearDown(self):
        """测试后清理"""
        shutil.rmtree(self.test_dir)
    
    def test_init(self):
        """测试初始化"""
        downloader = MediaDownloader(max_retries=5, timeout=60, chunk_size=4096)
        self.assertEqual(downloader.max_retries, 5)
        self.assertEqual(downloader.timeout, 60)
        self.assertEqual(downloader.chunk_size, 4096)
    
    def test_get_media_filename_image(self):
        """测试图片文件名生成"""
        url = "https://example.com/image.jpg"
        filename = self.downloader.get_media_filename(url, 1, 'image')
        self.assertEqual(filename, "image_01.jpg")
        
        # 测试没有扩展名的URL
        url_no_ext = "https://example.com/image"
        filename = self.downloader.get_media_filename(url_no_ext, 2, 'image')
        self.assertEqual(filename, "image_02.jpg")
    
    def test_get_media_filename_video(self):
        """测试视频文件名生成"""
        url = "https://example.com/video.mp4"
        filename = self.downloader.get_media_filename(url, 1, 'video')
        self.assertEqual(filename, "video_01.mp4")
        
        # 测试其他视频格式
        url_mov = "https://example.com/video.mov"
        filename = self.downloader.get_media_filename(url_mov, 3, 'video')
        self.assertEqual(filename, "video_03.mov")
    
    def test_get_media_filename_invalid_extension(self):
        """测试无效扩展名的处理"""
        # 图片URL但扩展名不是图片格式
        url = "https://example.com/file.txt"
        filename = self.downloader.get_media_filename(url, 1, 'image')
        self.assertEqual(filename, "image_01.jpg")  # 应该使用默认扩展名
        
        # 视频URL但扩展名不是视频格式
        filename = self.downloader.get_media_filename(url, 1, 'video')
        self.assertEqual(filename, "video_01.mp4")  # 应该使用默认扩展名
    
    def test_get_media_filename_malformed_url(self):
        """测试格式错误的URL"""
        malformed_url = "not_a_url"
        filename = self.downloader.get_media_filename(malformed_url, 1, 'image')
        self.assertEqual(filename, "image_01.jpg")
    
    @patch('services.media_downloader.requests.head')
    @patch('services.media_downloader.requests.get')
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.exists')
    @patch('os.path.getsize')
    @patch('os.makedirs')
    def test_download_file_success(self, mock_makedirs, mock_getsize, mock_exists, 
                                 mock_file_open, mock_get, mock_head):
        """测试文件下载成功"""
        # 模拟文件不存在
        mock_exists.return_value = False
        mock_getsize.return_value = 0
        
        # 模拟HEAD请求
        mock_head_response = Mock()
        mock_head_response.headers = {'content-length': '1024'}
        mock_head.return_value = mock_head_response
        
        # 模拟GET请求
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.iter_content.return_value = [b'test_data']
        mock_get.return_value = mock_response
        
        # 模拟文件存在且有内容
        def side_effect(path):
            return path.endswith('test.jpg')
        mock_exists.side_effect = side_effect
        mock_getsize.return_value = 100
        
        result = self.downloader._download_file(
            'https://example.com/test.jpg', 
            '/path/to/test.jpg'
        )
        
        self.assertTrue(result)
        mock_get.assert_called_once()
        mock_file_open.assert_called_once()
    
    @patch('services.media_downloader.requests.head')
    @patch('services.media_downloader.requests.get')
    def test_download_file_http_error(self, mock_get, mock_head):
        """测试HTTP错误处理"""
        mock_head.return_value = Mock(headers={'content-length': '1024'})
        
        # 模拟HTTP错误
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 404")
        mock_get.return_value = mock_response
        
        result = self.downloader._download_file(
            'https://example.com/nonexistent.jpg', 
            '/path/to/test.jpg'
        )
        
        self.assertFalse(result)
    
    @patch('os.path.exists')
    @patch('os.path.getsize')
    def test_download_file_already_exists(self, mock_getsize, mock_exists):
        """测试文件已存在的情况"""
        mock_exists.return_value = True
        mock_getsize.return_value = 1024  # 文件有内容
        
        result = self.downloader._download_file(
            'https://example.com/test.jpg', 
            '/path/to/existing.jpg'
        )
        
        self.assertTrue(result)
    
    @patch.object(MediaDownloader, '_download_file')
    @patch('os.makedirs')
    def test_download_images(self, mock_makedirs, mock_download):
        """测试图片下载"""
        mock_download.return_value = True
        
        urls = [
            'https://example.com/image1.jpg',
            'https://example.com/image2.png'
        ]
        
        result = self.downloader.download_images(urls, self.test_dir)
        
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], MediaFile)
        self.assertEqual(result[0].media_type, 'photo')
        self.assertEqual(mock_download.call_count, 2)
        mock_makedirs.assert_called_once()
    
    @patch.object(MediaDownloader, '_download_file')
    @patch('os.makedirs')
    def test_download_videos(self, mock_makedirs, mock_download):
        """测试视频下载"""
        mock_download.return_value = True
        
        urls = [
            'https://example.com/video1.mp4',
            'https://example.com/video2.mov'
        ]
        
        result = self.downloader.download_videos(urls, self.test_dir)
        
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], MediaFile)
        self.assertEqual(result[0].media_type, 'video')
        self.assertEqual(mock_download.call_count, 2)
        mock_makedirs.assert_called_once()
    
    def test_download_empty_list(self):
        """测试空URL列表"""
        result_images = self.downloader.download_images([], self.test_dir)
        result_videos = self.downloader.download_videos([], self.test_dir)
        
        self.assertEqual(len(result_images), 0)
        self.assertEqual(len(result_videos), 0)
    
    @patch.object(MediaDownloader, '_download_file')
    @patch('os.makedirs')
    def test_download_partial_failure(self, mock_makedirs, mock_download):
        """测试部分下载失败"""
        # 第一个成功，第二个失败
        mock_download.side_effect = [True, False]
        
        urls = [
            'https://example.com/image1.jpg',
            'https://example.com/image2.jpg'
        ]
        
        result = self.downloader.download_images(urls, self.test_dir)
        
        # 只有一个成功下载
        self.assertEqual(len(result), 1)
        self.assertEqual(mock_download.call_count, 2)
    
    @patch('services.media_downloader.requests.head')
    def test_get_file_size(self, mock_head):
        """测试获取文件大小"""
        mock_response = Mock()
        mock_response.headers = {'content-length': '2048'}
        mock_response.raise_for_status.return_value = None
        mock_head.return_value = mock_response
        
        size = self.downloader.get_file_size('https://example.com/file.jpg')
        self.assertEqual(size, 2048)
    
    @patch('services.media_downloader.requests.head')
    def test_get_file_size_failure(self, mock_head):
        """测试获取文件大小失败"""
        mock_head.side_effect = Exception("Network error")
        
        size = self.downloader.get_file_size('https://example.com/file.jpg')
        self.assertIsNone(size)
    
    @patch('services.media_downloader.requests.head')
    def test_validate_url(self, mock_head):
        """测试URL验证"""
        # 成功的情况
        mock_response = Mock()
        mock_response.status_code = 200
        mock_head.return_value = mock_response
        
        result = self.downloader.validate_url('https://example.com/valid.jpg')
        self.assertTrue(result)
        
        # 失败的情况
        mock_response.status_code = 404
        result = self.downloader.validate_url('https://example.com/invalid.jpg')
        self.assertFalse(result)
    
    @patch('services.media_downloader.requests.head')
    def test_validate_url_exception(self, mock_head):
        """测试URL验证异常"""
        mock_head.side_effect = Exception("Network error")
        
        result = self.downloader.validate_url('https://example.com/file.jpg')
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
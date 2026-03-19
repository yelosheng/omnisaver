import unittest
import os
import tempfile
import shutil
from unittest.mock import patch, mock_open
from services.config_manager import ConfigManager


class TestConfigManager(unittest.TestCase):
    """ConfigManager单元测试"""
    
    def setUp(self):
        """测试前准备"""
        self.test_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.test_dir, 'test_config.ini')
        
    def tearDown(self):
        """测试后清理"""
        shutil.rmtree(self.test_dir)
    
    def test_create_default_config(self):
        """测试创建默认配置文件"""
        config_manager = ConfigManager(self.config_file)
        self.assertTrue(os.path.exists(self.config_file))
        
        # 验证默认配置内容
        self.assertEqual(config_manager.get_save_path(), '/mnt/nas/saved_tweets')
        self.assertTrue(config_manager.get_create_date_folders())
        self.assertEqual(config_manager.get_max_retries(), 3)
        self.assertEqual(config_manager.get_timeout_seconds(), 30)
    
    @patch.dict(os.environ, {'TWITTER_BEARER_TOKEN': 'test_token_from_env'})
    def test_get_bearer_token_from_env(self):
        """测试从环境变量获取Bearer Token"""
        config_manager = ConfigManager(self.config_file)
        self.assertEqual(config_manager.get_bearer_token(), 'test_token_from_env')
    
    def test_get_bearer_token_missing(self):
        """测试Bearer Token缺失时的错误处理"""
        config_manager = ConfigManager(self.config_file)
        with self.assertRaises(ValueError) as context:
            config_manager.get_bearer_token()
        self.assertIn("Twitter Bearer Token not found", str(context.exception))
    
    @patch.dict(os.environ, {'SAVE_PATH': '/custom/path'})
    def test_get_save_path_from_env(self):
        """测试从环境变量获取保存路径"""
        config_manager = ConfigManager(self.config_file)
        self.assertEqual(config_manager.get_save_path(), '/custom/path')
    
    @patch.dict(os.environ, {'MAX_RETRIES': '5'})
    def test_get_max_retries_from_env(self):
        """测试从环境变量获取最大重试次数"""
        config_manager = ConfigManager(self.config_file)
        self.assertEqual(config_manager.get_max_retries(), 5)
    
    @patch.dict(os.environ, {'CREATE_DATE_FOLDERS': 'false'})
    def test_get_create_date_folders_from_env(self):
        """测试从环境变量获取日期文件夹设置"""
        config_manager = ConfigManager(self.config_file)
        self.assertFalse(config_manager.get_create_date_folders())
    
    def test_load_config(self):
        """测试加载完整配置"""
        with patch.dict(os.environ, {'TWITTER_BEARER_TOKEN': 'test_token'}):
            config_manager = ConfigManager(self.config_file)
            config = config_manager.load_config()
            
            self.assertIn('bearer_token', config)
            self.assertIn('save_path', config)
            self.assertIn('create_date_folders', config)
            self.assertIn('max_retries', config)
            self.assertIn('timeout_seconds', config)
    
    @patch.dict(os.environ, {'TWITTER_BEARER_TOKEN': 'test_token'})
    def test_validate_config_success(self):
        """测试配置验证成功"""
        config_manager = ConfigManager(self.config_file)
        # 设置保存路径为测试目录
        config_manager.config.set('storage', 'base_path', self.test_dir)
        self.assertTrue(config_manager.validate_config())
    
    def test_validate_config_failure(self):
        """测试配置验证失败"""
        config_manager = ConfigManager(self.config_file)
        # 不设置Bearer Token，应该验证失败
        self.assertFalse(config_manager.validate_config())


if __name__ == '__main__':
    unittest.main()
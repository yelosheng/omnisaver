import os
import configparser
from typing import Dict, Any, Optional
from utils.realtime_logger import info, error


class ConfigManager:
    """Configuration manager for handling config files"""

    def __init__(self, config_file: str = "config.ini"):
        self.config_file = config_file
        # Cookie values may contain URL-encoded `%xx` sequences; disable
        # interpolation so they are persisted verbatim in config.ini.
        self.config = configparser.ConfigParser(interpolation=None)
        self._load_config_file()
    
    def _load_config_file(self):
        """Load configuration file"""
        if os.path.exists(self.config_file):
            self.config.read(self.config_file, encoding='utf-8')
        else:
            self._create_default_config()
    
    def _create_default_config(self):
        """Create default configuration file"""
        self.config['storage'] = {
            'base_path': 'saved_tweets',
            'create_date_folders': 'true'
        }
        self.config['download'] = {
            'max_retries': '3',
            'timeout_seconds': '30'
        }
        self.config['scraper'] = {
            'use_playwright': 'true',
            'headless': 'true',
            'debug_mode': 'false'
        }
        self.config['ai'] = {
            'gemini_api_key': '',
            'youtube_api_key': ''
        }

        with open(self.config_file, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get_save_path(self) -> str:
        """Get save path — env var SAVE_PATH takes priority over config.ini"""
        env_path = os.environ.get('SAVE_PATH', '').strip()
        if env_path:
            return env_path
        return self.config.get('storage', 'base_path', fallback='saved_tweets')
    
    def get_create_date_folders(self) -> bool:
        """Whether to create date folders"""
        return self.config.getboolean('storage', 'create_date_folders', fallback=True)
    
    def get_max_retries(self) -> int:
        """Get maximum retry attempts"""
        return self.config.getint('download', 'max_retries', fallback=3)
    
    def get_timeout_seconds(self) -> int:
        """Get timeout (seconds)"""
        return self.config.getint('download', 'timeout_seconds', fallback=30)
    
    def get_use_playwright(self) -> bool:
        """Get whether to use Playwright"""
        return self.config.getboolean('scraper', 'use_playwright', fallback=True)
    
    def get_playwright_headless(self) -> bool:
        """Get whether Playwright uses headless mode"""
        return self.config.getboolean('scraper', 'headless', fallback=True)
    
    def get_playwright_debug(self) -> bool:
        """Get whether Playwright enables debug mode"""
        return self.config.getboolean('scraper', 'debug_mode', fallback=False)

    def get_twitter_auth_token(self) -> Optional[str]:
        """Get Twitter auth_token cookie for xreach"""
        token = self.config.get('twitter', 'auth_token', fallback='')
        return token if token else None

    def get_twitter_ct0(self) -> Optional[str]:
        """Get Twitter ct0 cookie for xreach"""
        ct0 = self.config.get('twitter', 'ct0', fallback='')
        return ct0 if ct0 else None

    def set_twitter_cookies(self, auth_token: str, ct0: str) -> None:
        """Persist Twitter auth_token and ct0 to config file"""
        if 'twitter' not in self.config:
            self.config['twitter'] = {}
        self.config['twitter']['auth_token'] = auth_token
        self.config['twitter']['ct0'] = ct0
        self._save()

    def get_gemini_api_key(self) -> Optional[str]:
        """Get Gemini API key"""
        api_key = self.config.get('ai', 'gemini_api_key', fallback='')
        return api_key if api_key else None

    def get_youtube_api_key(self) -> Optional[str]:
        """Get YouTube Data API v3 key (config file or YOUTUBE_API_KEY env var)"""
        api_key = self.config.get('ai', 'youtube_api_key', fallback='')
        if not api_key:
            api_key = os.environ.get('YOUTUBE_API_KEY', '')
        return api_key if api_key else None

    def set_youtube_api_key(self, api_key: str) -> None:
        """Persist YouTube Data API v3 key to config file"""
        if 'ai' not in self.config:
            self.config['ai'] = {}
        self.config['ai']['youtube_api_key'] = api_key
        with open(self.config_file, 'w', encoding='utf-8') as f:
            self.config.write(f)
    def load_config(self) -> Dict[str, Any]:
        """Load all configuration and return dictionary"""
        return {
            'save_path': self.get_save_path(),
            'create_date_folders': self.get_create_date_folders(),
            'max_retries': self.get_max_retries(),
            'timeout_seconds': self.get_timeout_seconds(),
            'use_playwright': self.get_use_playwright(),
            'playwright_headless': self.get_playwright_headless(),
            'playwright_debug': self.get_playwright_debug()
        }
    
    def _save(self):
        """Write config back to file"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def set_save_path(self, path: str) -> None:
        if 'storage' not in self.config:
            self.config['storage'] = {}
        self.config['storage']['base_path'] = path
        self._save()

    def set_create_date_folders(self, value: bool) -> None:
        if 'storage' not in self.config:
            self.config['storage'] = {}
        self.config['storage']['create_date_folders'] = 'true' if value else 'false'
        self._save()

    def set_max_retries(self, value: int) -> None:
        if 'download' not in self.config:
            self.config['download'] = {}
        self.config['download']['max_retries'] = str(value)
        self._save()

    def set_timeout_seconds(self, value: int) -> None:
        if 'download' not in self.config:
            self.config['download'] = {}
        self.config['download']['timeout_seconds'] = str(value)
        self._save()

    def get_config(self, section: str, key: str, fallback: Any = None) -> Any:
        """Generic config getter."""
        return self.config.get(section, key, fallback=fallback)

    def set_config(self, section: str, key: str, value: str) -> None:
        """Generic config setter."""
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value
        self._save()

    def set_playwright_headless(self, value: bool) -> None:
        if 'scraper' not in self.config:
            self.config['scraper'] = {}
        self.config['scraper']['headless'] = 'true' if value else 'false'
        self._save()

    def validate_config(self) -> bool:
        """Validate if configuration is valid"""
        try:
            # Check if save path is writable
            save_path = self.get_save_path()
            os.makedirs(save_path, exist_ok=True)
            test_file = os.path.join(save_path, '.test_write')
            try:
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
            except (OSError, IOError) as e:
                raise ValueError(f"Cannot write to save path {save_path}: {e}")

            info("[Config] Using web scraping mode (Playwright browser automation)")

            return True
        except ValueError as e:
            error(f"[Config] Configuration error: {e}")
            return False

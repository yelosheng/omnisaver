import re
from typing import Optional
from urllib.parse import urlparse


class TwitterURLParser:
    """Twitter URL解析器"""
    
    # 支持的Twitter URL格式
    URL_PATTERNS = [
        # https://twitter.com/username/status/1234567890
        r'https?://(?:www\.)?twitter\.com/[^/]+/status/(\d+)',
        # https://x.com/username/status/1234567890
        r'https?://(?:www\.)?x\.com/[^/]+/status/(\d+)',
        # https://mobile.twitter.com/username/status/1234567890
        r'https?://mobile\.twitter\.com/[^/]+/status/(\d+)',
        # https://m.twitter.com/username/status/1234567890
        r'https?://m\.twitter\.com/[^/]+/status/(\d+)',
        # https://fxtwitter.com/username/status/1234567890
        r'https?://(?:www\.)?fxtwitter\.com/[^/]+/status/(\d+)',
        # https://fixupx.com/username/status/1234567890 (另一个常见的转换域名)
        r'https?://(?:www\.)?fixupx\.com/[^/]+/status/(\d+)',
        # https://x.com/username/article/1234567890 (X长文)
        r'https?://(?:www\.)?x\.com/[^/]+/article/(\d+)',
        # https://twitter.com/username/article/1234567890
        r'https?://(?:www\.)?twitter\.com/[^/]+/article/(\d+)',
    ]

    # 长文 article URL 格式
    ARTICLE_URL_PATTERNS = [
        r'https?://(?:www\.)?x\.com/[^/]+/article/(\d+)',
        r'https?://(?:www\.)?twitter\.com/[^/]+/article/(\d+)',
    ]
    
    @classmethod
    def extract_tweet_id(cls, url: str) -> Optional[str]:
        """
        从Twitter URL中提取推文ID
        
        Args:
            url: Twitter URL字符串
            
        Returns:
            推文ID字符串，如果无法解析则返回None
        """
        if not url or not isinstance(url, str):
            return None
        
        # 清理URL，移除多余的空格和参数
        url = url.strip()
        
        # 移除URL中的查询参数和片段
        parsed = urlparse(url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        
        # 尝试匹配各种URL格式
        for pattern in cls.URL_PATTERNS:
            match = re.match(pattern, clean_url, re.IGNORECASE)
            if match:
                tweet_id = match.group(1)
                # 验证推文ID格式（应该是数字且长度合理）
                if cls._is_valid_tweet_id(tweet_id):
                    return tweet_id
        
        return None
    
    @classmethod
    def _is_valid_tweet_id(cls, tweet_id: str) -> bool:
        """
        验证推文ID格式
        
        Args:
            tweet_id: 推文ID字符串
            
        Returns:
            是否为有效的推文ID
        """
        if not tweet_id or not tweet_id.isdigit():
            return False
        
        # Twitter推文ID通常是19位数字（雪花算法生成）
        # 但早期的推文ID可能较短，所以我们允许10-20位
        return 10 <= len(tweet_id) <= 20
    
    @classmethod
    def is_valid_twitter_url(cls, url: str) -> bool:
        """
        验证是否为有效的Twitter URL
        
        Args:
            url: URL字符串
            
        Returns:
            是否为有效的Twitter URL（包括长文 article URL）
        """
        return cls.extract_tweet_id(url) is not None

    @classmethod
    def is_article_url(cls, url: str) -> bool:
        """
        判断是否为X长文（article）URL

        Args:
            url: URL字符串

        Returns:
            是否为长文 article URL
        """
        if not url or not isinstance(url, str):
            return False
        url = url.strip()
        parsed = urlparse(url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        for pattern in cls.ARTICLE_URL_PATTERNS:
            if re.match(pattern, clean_url, re.IGNORECASE):
                return True
        return False
    
    @classmethod
    def normalize_url(cls, url: str) -> Optional[str]:
        """
        标准化Twitter URL，保留用户名信息以确保媒体正确加载
        对于长文 article URL，保留 article 格式以便正确抓取内容。
        
        Args:
            url: 原始Twitter URL
            
        Returns:
            标准化后的URL，如果无法解析则返回None
        """
        tweet_id = cls.extract_tweet_id(url)
        if not tweet_id:
            return None

        # 尝试提取用户名
        username = cls.extract_username(url)

        # 如果是长文 article URL，保留 article 路径
        if cls.is_article_url(url):
            if username:
                return f"https://x.com/{username}/article/{tweet_id}"
            else:
                return f"https://x.com/i/web/status/{tweet_id}"
        
        if username:
            # 返回包含用户名的标准格式URL（确保媒体正确加载）
            return f"https://x.com/{username}/status/{tweet_id}"
        else:
            # 如果无法提取用户名，使用通用格式但不要返回None
            return f"https://x.com/i/web/status/{tweet_id}"
    
    @classmethod
    def extract_username(cls, url: str) -> Optional[str]:
        """
        从Twitter URL中提取用户名
        
        Args:
            url: Twitter URL字符串
            
        Returns:
            用户名字符串，如果无法解析则返回None
        """
        if not url or not isinstance(url, str):
            return None
        
        # 清理URL
        url = url.strip()
        from urllib.parse import urlparse
        parsed = urlparse(url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        
        # 用于提取用户名的正则表达式模式（支持 status 和 article 路径）
        username_patterns = [
            r'https?://(?:www\.)?(?:twitter|x)\.com/([^/]+)/(?:status|article)/\d+',
            r'https?://(?:mobile|m)\.twitter\.com/([^/]+)/(?:status|article)/\d+',
            r'https?://(?:www\.)?(?:fxtwitter|fixupx)\.com/([^/]+)/status/\d+',
        ]
        
        for pattern in username_patterns:
            match = re.match(pattern, clean_url, re.IGNORECASE)
            if match:
                username = match.group(1)
                # 验证用户名格式（排除特殊路径如"i", "web"等）
                if username and username not in ['i', 'web', 'intent', 'share']:
                    return username
        
        return None
    
    @classmethod
    def get_supported_formats(cls) -> list:
        """
        获取支持的URL格式示例
        
        Returns:
            支持的URL格式列表
        """
        return [
            "https://twitter.com/username/status/1234567890",
            "https://x.com/username/status/1234567890",
            "https://mobile.twitter.com/username/status/1234567890",
            "https://m.twitter.com/username/status/1234567890",
            "https://fxtwitter.com/username/status/1234567890",
            "https://fixupx.com/username/status/1234567890",
            "https://x.com/username/article/1234567890",
            "https://twitter.com/username/article/1234567890",
        ]
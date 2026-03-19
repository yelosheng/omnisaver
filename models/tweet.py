from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class Tweet:
    """推文数据模型"""
    id: str
    text: str
    html_content: Optional[str]  # 原始HTML格式内容
    author_username: str
    author_name: str
    created_at: datetime
    media_urls: List[str]
    media_types: List[str]  # ['photo', 'video', 'animated_gif']
    reply_to: Optional[str]
    conversation_id: str
    
    def __post_init__(self):
        """数据验证"""
        if not self.id:
            raise ValueError("Tweet ID cannot be empty")
        if not self.author_username:
            raise ValueError("Author username cannot be empty")
        if len(self.media_urls) != len(self.media_types):
            raise ValueError("Media URLs and types must have the same length")
    
    def has_media(self) -> bool:
        """检查推文是否包含媒体文件"""
        return len(self.media_urls) > 0
    
    def get_images(self) -> List[str]:
        """获取图片URL列表"""
        return [url for url, media_type in zip(self.media_urls, self.media_types) 
                if media_type == 'photo']
    
    def get_videos(self) -> List[str]:
        """获取视频URL列表"""
        return [url for url, media_type in zip(self.media_urls, self.media_types) 
                if media_type in ['video', 'animated_gif']]
    
    def get_avatars(self) -> List[str]:
        """获取头像URL列表"""
        return [url for url, media_type in zip(self.media_urls, self.media_types) 
                if media_type == 'avatar']
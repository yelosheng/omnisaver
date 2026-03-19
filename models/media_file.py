from dataclasses import dataclass


@dataclass
class MediaFile:
    """媒体文件数据模型"""
    url: str
    local_path: str
    media_type: str
    filename: str
    
    def __post_init__(self):
        """数据验证"""
        if not self.url:
            raise ValueError("Media URL cannot be empty")
        if not self.local_path:
            raise ValueError("Local path cannot be empty")
        if self.media_type not in ['photo', 'video', 'animated_gif']:
            raise ValueError(f"Invalid media type: {self.media_type}")
        if not self.filename:
            raise ValueError("Filename cannot be empty")
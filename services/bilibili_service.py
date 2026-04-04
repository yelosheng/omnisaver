import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

from utils.realtime_logger import info, warning, success

# Ensure pyenv yt-dlp is on PATH
_EXTRA_PATH_DIRS = [
    os.path.expanduser('~/.pyenv/shims'),
    os.path.expanduser('~/.pyenv/versions/3.11.9/bin'),
    os.path.expanduser('~/.npm-global/bin'),
]
for _p in _EXTRA_PATH_DIRS:
    if _p not in os.environ.get('PATH', ''):
        os.environ['PATH'] = _p + ':' + os.environ.get('PATH', '')


class BilibiliServiceError(Exception):
    pass


class BilibiliService:
    """Bilibili (哔哩哔哩) video downloader service."""

    _URL_RE = re.compile(
        r'https?://(?:www\.|m\.)?bilibili\.com/video/(BV[A-Za-z0-9]+|av\d+)'
        r'|https?://b23\.tv/[A-Za-z0-9]+'
    )

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir) / 'saved_bilibili')
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    @classmethod
    def is_valid_bilibili_url(cls, url: str) -> bool:
        return bool(cls._URL_RE.search(url))

    @classmethod
    def extract_url_from_share_text(cls, text: str) -> str:
        """
        Extract a Bilibili URL from a share text blob.
        Example: '【xxx】 https://b23.tv/c6tXBK8' -> 'https://b23.tv/c6tXBK8'
        """
        m = cls._URL_RE.search(text)
        return m.group(0) if m else ''

    @staticmethod
    def resolve_short_url(url: str) -> str:
        """Follow b23.tv short URL redirects."""
        if 'b23.tv' not in url:
            return url
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.url
        except Exception as e:
            warning(f"Could not resolve Bilibili short URL {url}: {e}")
            return url

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def save_video(self, url: str) -> dict:
        """
        Download a Bilibili video and save it locally.
        """
        if not self.is_valid_bilibili_url(url):
            raise BilibiliServiceError(f'Invalid Bilibili URL: {url}')

        url = self.resolve_short_url(url)
        info(f'Fetching Bilibili metadata: {url}')

        # --- metadata ---
        # Note: Bilibili often needs a specific User-Agent and Referer
        meta_cmd = [
            'yt-dlp', '--dump-json', '--no-playlist',
            '--no-check-certificate',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            '--add-header', 'Referer:https://www.bilibili.com/',
            url
        ]
        meta_result = subprocess.run(meta_cmd, capture_output=True, text=True, timeout=60)
        
        if meta_result.returncode != 0:
            err = meta_result.stderr.strip()[:300]
            # Try once more without extra headers if it failed
            warning(f"yt-dlp metadata failed with headers, retrying simple: {err}")
            meta_result = subprocess.run(['yt-dlp', '--dump-json', '--no-playlist', url], capture_output=True, text=True, timeout=60)
            
        if meta_result.returncode != 0:
            raise BilibiliServiceError(f'yt-dlp metadata failed: {meta_result.stderr.strip()[:300]}')
            
        meta = json.loads(meta_result.stdout)

        video_id = meta.get('id', '')
        title = meta.get('title', 'untitled')
        uploader = meta.get('uploader') or meta.get('channel', '')
        uploader_id = meta.get('uploader_id') or meta.get('channel_id', '')
        description = meta.get('description', '')
        upload_date = meta.get('upload_date', '')  # YYYYMMDD
        view_count = meta.get('view_count', 0)
        duration = meta.get('duration_string') or str(meta.get('duration', ''))

        # Parse upload date for folder naming
        now = datetime.now()
        pub_date = now
        if upload_date and len(upload_date) == 8:
            try:
                pub_date = datetime.strptime(upload_date, '%Y%m%d')
            except ValueError:
                pass

        date_str = pub_date.strftime('%Y-%m-%d')
        safe_title_path = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", title)[:40].strip()
        folder_name = f'{date_str}_{safe_title_path}_{video_id}'
        
        if self.create_date_folders:
            post_dir = self.base_path / pub_date.strftime('%Y-%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # --- download video ---
        info(f'Downloading Bilibili video: {title}')
        vid_dir = post_dir / 'videos'
        vid_dir.mkdir(exist_ok=True)
        video_file = vid_dir / 'video.mp4'
        
        with tempfile.TemporaryDirectory(prefix='bili_') as tmp_dir:
            tmp_out = os.path.join(tmp_dir, 'video.mp4')
            dl_cmd = [
                'yt-dlp', '--no-playlist', '--no-check-certificate',
                '--merge-output-format', 'mp4',
                '-o', tmp_out,
                url
            ]
            dl_result = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=600)
            if dl_result.returncode != 0:
                raise BilibiliServiceError(f'yt-dlp download failed: {dl_result.stderr[-500:]}')
            shutil.move(tmp_out, str(video_file))

        # --- thumbnail ---
        thumb_dir = post_dir / 'thumbnails'
        thumb_dir.mkdir(exist_ok=True)
        subprocess.run(
            ['yt-dlp', '--skip-download', '--write-thumbnail', '--no-check-certificate',
             '-o', str(thumb_dir / 'cover'), url],
            capture_output=True, timeout=30
        )
        
        # --- avatar ---
        avatar_url = meta.get('uploader_url') # yt-dlp doesn't always give avatar
        # We'll skip avatar for now or try to get from meta if available
        
        # --- content.txt ---
        (post_dir / 'content.txt').write_text(description, encoding='utf-8')

        # --- content.md ---
        safe_desc = re.sub(r'(?m)^#', r'\#', description)
        safe_title = re.sub(r'^#', r'\#', title)
        
        md = '\n'.join([
            f'# {safe_title}',
            '',
            f'**作者**: {uploader}  ',
            f'**发布时间**: {date_str}  ',
            f'**时长**: {duration}  ',
            f'**来源**: {url}  ',
            '',
            '[视频](videos/video.mp4)',
            '',
            '---',
            '',
            safe_desc,
        ])
        (post_dir / 'content.md').write_text(md, encoding='utf-8')

        # --- metadata.json ---
        (post_dir / 'metadata.json').write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        success(f'Bilibili video saved to {post_dir}')
        return {
            'video_id': video_id,
            'title': title,
            'save_path': str(post_dir),
            'author_username': uploader_id,
            'author_name': uploader,
            'tweet_text': description[:500],
            'media_count': 1,
        }

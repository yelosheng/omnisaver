import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from utils.realtime_logger import info, warning, success

_EXTRA_PATH_DIRS = [
    os.path.expanduser('~/.pyenv/shims'),
    os.path.expanduser('~/.pyenv/versions/3.11.9/bin'),
    os.path.expanduser('~/.npm-global/bin'),
]
for _p in _EXTRA_PATH_DIRS:
    if _p not in os.environ.get('PATH', ''):
        os.environ['PATH'] = _p + ':' + os.environ.get('PATH', '')


class DouyinServiceError(Exception):
    pass


class DouyinService:
    """Douyin (抖音) and TikTok video downloader service using yt-dlp."""

    _URL_RE = re.compile(
        r'https?://(?:'
        r'(?:www\.|m\.)?douyin\.com/video/\d+'
        r'|v\.douyin\.com/[\w/-]+'
        r'|(?:www\.)?tiktok\.com/@[^/]+/video/\d+'
        r'|vm\.tiktok\.com/[\w/-]+'
        r')'
    )

    def __init__(self, base_path: str = None, create_date_folders: bool = True,
                 douyin_cookie: str = None):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir))
        self.base_path = Path(base_path) / 'saved_douyin'
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders
        self.douyin_cookie = douyin_cookie or ''

    @classmethod
    def is_valid_douyin_url(cls, url: str) -> bool:
        return bool(cls._URL_RE.search(url))

    @classmethod
    def extract_url_from_share_text(cls, text: str) -> str:
        """
        Extract a Douyin/TikTok URL from a mobile share text blob, e.g.:
        '0.05 复制打开抖音，看看【xxx】... https://v.douyin.com/6uwbmz1XbMc/ 12/05 gOK:/'
        Returns the first matched URL, or '' if none found.
        """
        m = cls._URL_RE.search(text)
        return m.group(0).rstrip('/') + '/' if m else ''

    def _yt_dlp_args(self, extra: list = None) -> list:
        """Build base yt-dlp argument list with cookie header if configured."""
        args = ['yt-dlp']
        if self.douyin_cookie:
            args += ['--add-headers', f'Cookie:{self.douyin_cookie}']
        if extra:
            args += extra
        return args

    def save_video(self, url: str) -> dict:
        """
        Download a Douyin/TikTok video and save it locally.

        Directory layout:
          videos/video.mp4
          thumbnails/cover.jpg
          content.md
          content.txt
          metadata.json

        Returns dict with: video_id, title, save_path,
                           author_username, author_name, tweet_text, media_count
        """
        if not self.is_valid_douyin_url(url):
            raise DouyinServiceError(f'Invalid Douyin/TikTok URL: {url}')

        info(f'Fetching Douyin/TikTok metadata: {url}')

        # --- metadata ---
        meta_cmd = self._yt_dlp_args(['--dump-json', '--no-playlist', url])
        meta_result = subprocess.run(
            meta_cmd, capture_output=True, text=True, timeout=60
        )
        if meta_result.returncode != 0:
            raise DouyinServiceError(
                f'yt-dlp metadata failed: {meta_result.stderr.strip()[:300]}'
            )
        meta = json.loads(meta_result.stdout)

        video_id = str(meta.get('id', ''))
        title = meta.get('title') or meta.get('description', 'untitled')
        title = title[:60].strip() or 'untitled'
        uploader = meta.get('uploader') or meta.get('channel', '')
        uploader_id = meta.get('uploader_id') or meta.get('channel_id', '')
        description = meta.get('description', '')
        upload_date = meta.get('upload_date', '')  # YYYYMMDD
        duration = meta.get('duration_string') or str(meta.get('duration', ''))

        # Parse upload date for folder naming
        pub_date = datetime.now()
        if upload_date and len(upload_date) == 8:
            try:
                pub_date = datetime.strptime(upload_date, '%Y%m%d')
            except ValueError:
                pass

        date_str = pub_date.strftime('%Y-%m-%d')
        safe_title = re.sub(r'[^\w\u4e00-\u9fff\- ]', '', title)[:40].strip()
        folder_name = f'{date_str}_{safe_title}_{video_id}'
        if self.create_date_folders:
            post_dir = self.base_path / pub_date.strftime('%Y-%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # --- download video ---
        info(f'Downloading video: {title}')
        vid_dir = post_dir / 'videos'
        vid_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='douyin_') as tmp_dir:
            tmp_out = os.path.join(tmp_dir, 'video.mp4')
            err_log = os.path.join(tmp_dir, 'stderr.txt')
            dl_cmd = self._yt_dlp_args([
                '--no-playlist',
                '--no-continue', '--no-part',
                '--retries', '5', '--fragment-retries', '5',
                '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                '--merge-output-format', 'mp4',
                '-o', tmp_out,
                url,
            ])
            with open(err_log, 'w') as _ef:
                dl_result = subprocess.run(
                    dl_cmd, stdout=subprocess.DEVNULL, stderr=_ef, timeout=600
                )
            if dl_result.returncode != 0:
                err_text = Path(err_log).read_text(encoding='utf-8', errors='replace')[-500:]
                raise DouyinServiceError(f'yt-dlp download failed: {err_text}')
            shutil.move(tmp_out, str(vid_dir / 'video.mp4'))

        # --- thumbnail ---
        thumb_dir = post_dir / 'thumbnails'
        thumb_dir.mkdir(exist_ok=True)
        thumb_cmd = self._yt_dlp_args([
            '--skip-download', '--write-thumbnail',
            '--convert-thumbnails', 'jpg',
            '-o', str(thumb_dir / 'cover'),
            url,
        ])
        subprocess.run(thumb_cmd, capture_output=True, timeout=30)
        # yt-dlp may add extension; check for any image file
        for ext in ('jpg', 'png', 'webp'):
            candidate = thumb_dir / f'cover.{ext}'
            if candidate.exists():
                break

        # --- content.txt ---
        (post_dir / 'content.txt').write_text(description, encoding='utf-8')

        # --- content.md ---
        md = '\n'.join([
            f'# {title}',
            '',
            f'**作者**: {uploader}  ',
            f'**发布时间**: {date_str}  ',
            f'**时长**: {duration}  ' if duration else '',
            f'**来源**: {url}  ',
            '',
            '[视频](videos/video.mp4)',
            '',
            '---',
            '',
            description,
        ])
        (post_dir / 'content.md').write_text(md, encoding='utf-8')

        # --- metadata.json ---
        keep_keys = {
            'id', 'title', 'description', 'upload_date',
            'uploader', 'uploader_id', 'channel', 'channel_id',
            'duration', 'duration_string',
            'view_count', 'like_count', 'comment_count',
            'thumbnail', 'webpage_url',
        }
        trimmed_meta = {k: v for k, v in meta.items() if k in keep_keys}
        trimmed_meta['platform'] = 'douyin'
        trimmed_meta['saved_at'] = datetime.now().isoformat()
        (post_dir / 'metadata.json').write_text(
            json.dumps(trimmed_meta, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        success(f'Douyin/TikTok video saved to {post_dir}')
        return {
            'video_id': video_id,
            'title': title,
            'save_path': str(post_dir),
            'author_username': uploader_id,
            'author_name': uploader,
            'tweet_text': description[:500],
            'media_count': 1,
        }

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

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


class InstagramServiceError(Exception):
    pass


class InstagramService:
    """Instagram video (Reels/Posts) downloader service."""

    _URL_RE = re.compile(
        r'https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/([\w-]+)'
    )

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir))
        self.base_path = Path(base_path) / 'saved_instagram'
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    @classmethod
    def is_valid_instagram_url(cls, url: str) -> bool:
        return bool(cls._URL_RE.search(url))

    @classmethod
    def extract_url_from_share_text(cls, text: str) -> str:
        """
        Extract an Instagram URL from a share text blob.
        """
        m = cls._URL_RE.search(text)
        return m.group(0) if m else ''

    async def _fetch_avatar_async(self, url: str) -> str:
        """Use Playwright to find the uploader avatar URL from the page DOM."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            # Use a modern mobile UA to avoid some login walls
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
            )
            page = await context.new_page()
            
            try:
                # Instagram is heavy, wait for some time
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(3)
                
                avatar_url = await page.evaluate('''() => {
                    // Look for common avatar patterns in IG
                    const img = document.querySelector('header img, canvas + img, img[alt*="profile picture"]');
                    return img ? img.src : "";
                }''')
                
                return avatar_url
            except Exception as e:
                warning(f"Instagram avatar extraction failed: {e}")
                return ""
            finally:
                await browser.close()

    def _download_file(self, url: str, dest_path: Path):
        """Helper to download a file with urllib."""
        if not url: return
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Referer': 'https://www.instagram.com/'
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as response, open(dest_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)

    def save_video(self, url: str) -> dict:
        """
        Download an Instagram video/post and save it locally.
        """
        if not self.is_valid_instagram_url(url):
            raise InstagramServiceError(f'Invalid Instagram URL: {url}')

        # Clean URL
        m = self._URL_RE.search(url)
        video_id = m.group(1)
        url = f"https://www.instagram.com/reel/{video_id}/"

        info(f'Fetching Instagram metadata: {url}')

        # 1. Get Metadata via yt-dlp
        meta_result = subprocess.run(
            ['yt-dlp', '--dump-json', '--no-playlist', url],
            capture_output=True, text=True, timeout=60
        )
        if meta_result.returncode != 0:
            # Try once more with a common referer
            meta_result = subprocess.run(
                ['yt-dlp', '--dump-json', '--no-playlist', '--referer', 'https://www.instagram.com/', url],
                capture_output=True, text=True, timeout=60
            )
            
        if meta_result.returncode != 0:
            raise InstagramServiceError(
                f'yt-dlp metadata failed: {meta_result.stderr.strip()[:300]}'
            )
        
        meta = json.loads(meta_result.stdout)
        
        uploader = meta.get('uploader') or meta.get('channel') or 'Instagram User'
        uploader_id = meta.get('uploader_id') or uploader
        description = meta.get('description') or meta.get('title') or 'No description'
        upload_date = meta.get('upload_date', '') # YYYYMMDD
        
        # Date parsing
        now = datetime.now()
        pub_date = now
        if upload_date and len(upload_date) == 8:
            try:
                pub_date = datetime.strptime(upload_date, '%Y%m%d')
            except: pass
        
        date_str = pub_date.strftime('%Y-%m-%d')
        
        # Directory creation
        safe_desc = re.sub(r'[^\w\u4e00-\u9fff\- ]', '', description)[:40].strip() or 'instagram_video'
        folder_name = f'{date_str}_{safe_desc}_{video_id}'
        if self.create_date_folders:
            post_dir = self.base_path / pub_date.strftime('%Y-%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # 2. Download Video
        info(f'Downloading Instagram video: {uploader}')
        vid_dir = post_dir / 'videos'
        vid_dir.mkdir(exist_ok=True)
        
        # Use yt-dlp for actual download
        with tempfile.TemporaryDirectory(prefix='ig_') as tmp_dir:
            tmp_out = os.path.join(tmp_dir, 'video.mp4')
            dl_result = subprocess.run(
                ['yt-dlp', '--no-playlist', '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                 '--merge-output-format', 'mp4', '-o', tmp_out, url],
                capture_output=True, timeout=300
            )
            if dl_result.returncode == 0 and os.path.exists(tmp_out):
                shutil.move(tmp_out, str(vid_dir / 'video.mp4'))
            else:
                # Check if it's an image post (yt-dlp sometimes fails on images for IG)
                if 'formats' not in meta or not meta['formats']:
                    warning("yt-dlp found no video formats, might be an image post.")
                else:
                    raise InstagramServiceError(f"yt-dlp download failed: {dl_result.stderr.decode()[:200]}")

        # 3. Download Thumbnail
        thumb_url = meta.get('thumbnail')
        if thumb_url:
            thumb_dir = post_dir / 'thumbnails'
            thumb_dir.mkdir(exist_ok=True)
            try:
                self._download_file(thumb_url, thumb_dir / 'cover.jpg')
            except Exception as e:
                warning(f"Thumbnail download failed: {e}")

        # 4. Fetch Avatar via Playwright
        avatar_url = asyncio.run(self._fetch_avatar_async(url))
        if avatar_url:
            try:
                self._download_file(avatar_url, post_dir / 'avatar.jpg')
            except Exception as e:
                warning(f"Avatar download failed: {e}")

        # --- content.txt ---
        (post_dir / 'content.txt').write_text(description, encoding='utf-8')

        # --- content.md ---
        safe_description_md = re.sub(r'(?m)^#', r'\#', description)
        md = '\n'.join([
            f'# Instagram Post by {uploader}',
            '',
            f'**作者**: {uploader}  ',
            f'**发布时间**: {date_str}  ',
            f'**来源**: {url}  ',
            '',
            '[视频](videos/video.mp4)' if (vid_dir / 'video.mp4').exists() else '',
            '',
            '---',
            '',
            safe_description_md,
        ])
        (post_dir / 'content.md').write_text(md, encoding='utf-8')

        # --- metadata.json ---
        metadata = {
            'id': video_id,
            'title': description[:100],
            'description': description,
            'uploader': uploader,
            'uploader_id': uploader_id,
            'url': url,
            'platform': 'instagram',
            'saved_at': datetime.now().isoformat(),
            'avatar': avatar_url,
            'thumbnail': thumb_url
        }
        (post_dir / 'metadata.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        success(f'Instagram content saved to {post_dir}')
        return {
            'video_id': video_id,
            'title': description[:100],
            'save_path': str(post_dir),
            'author_username': uploader_id,
            'author_name': uploader,
            'tweet_text': description[:500],
            'media_count': 1 if (vid_dir / 'video.mp4').exists() else 0,
        }

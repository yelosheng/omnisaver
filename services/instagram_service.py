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
    """Instagram video/image/carousel downloader service."""

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
        m = cls._URL_RE.search(text)
        return m.group(0) if m else ''

    async def _fetch_metadata_playwright(self, url: str) -> dict:
        """Use Playwright as a robust fallback for metadata and avatar."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
            )
            page = await context.new_page()
            
            meta = {'avatar': '', 'images': [], 'author': '', 'desc': ''}
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(4)
                
                res = await page.evaluate('''() => {
                    const getTxt = (s) => document.querySelector(s)?.innerText?.trim() || "";
                    
                    // Avatar: look for profile pic in header or specific IG classes
                    const avatarImg = document.querySelector('header img, canvas + img, img[alt*="profile picture"], img._aa8j');
                    const avatar = avatarImg ? avatarImg.src : "";
                    
                    // Author
                    const author = getTxt('header h2, header span, a._acan');
                    
                    // Description
                    const desc = getTxt('div._a9zs, h1._ap3a');
                    
                    // All images (for carousel) - filter out small icons
                    const imgs = Array.from(document.querySelectorAll('img'))
                        .map(img => img.src)
                        .filter(src => src.includes('scontent') && !src.includes('150x150'));
                    
                    return { avatar, author, desc, images: [...new Set(imgs)] };
                }''')
                meta.update(res)
            except Exception as e:
                warning(f"Instagram Playwright extraction failed: {e}")
            finally:
                await browser.close()
            return meta

    def _download_file(self, url: str, dest_path: Path):
        if not url: return
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Referer': 'https://www.instagram.com/'
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as response, open(dest_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
        except Exception as e:
            warning(f"Download failed for {url}: {e}")

    def save_video(self, url: str) -> dict:
        if not self.is_valid_instagram_url(url):
            raise InstagramServiceError(f'Invalid Instagram URL: {url}')

        # Normalize URL but keep /p/ or /reel/
        m = self._URL_RE.search(url)
        video_id = m.group(1)
        # Keep original type if possible, default to /p/ for generic support
        clean_url = url.split('?')[0].rstrip('/') + '/'

        info(f'Fetching Instagram metadata: {clean_url}')

        # 1. Get Metadata via yt-dlp
        meta = {}
        try:
            # Add referer to bypass simple blocks
            cmd = ['yt-dlp', '--dump-json', '--no-playlist', '--referer', 'https://www.instagram.com/', clean_url]
            meta_result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if meta_result.returncode == 0:
                meta = json.loads(meta_result.stdout)
        except Exception as e:
            warning(f"yt-dlp metadata failed: {e}")

        # 2. Get Avatar and Fallback metadata via Playwright
        pw_meta = asyncio.run(self._fetch_metadata_playwright(clean_url))
        
        uploader = meta.get('uploader') or pw_meta.get('author') or 'Instagram User'
        uploader_id = meta.get('uploader_id') or uploader
        description = meta.get('description') or meta.get('title') or pw_meta.get('desc') or 'No description'
        upload_date = meta.get('upload_date', '')
        
        now = datetime.now()
        pub_date = now
        if upload_date and len(upload_date) == 8:
            try: pub_date = datetime.strptime(upload_date, '%Y%m%d')
            except: pass
        
        date_str = pub_date.strftime('%Y-%m-%d')
        safe_desc = re.sub(r'[^\w\u4e00-\u9fff\- ]', '', description)[:40].strip() or 'instagram_post'
        folder_name = f'{date_str}_{safe_desc}_{video_id}'
        
        post_dir = (self.base_path / pub_date.strftime('%Y-%m') / folder_name) if self.create_date_folders else (self.base_path / folder_name)
        post_dir.mkdir(parents=True, exist_ok=True)

        media_count = 0

        # 3. Download Video if exists
        vid_dir = post_dir / 'videos'
        vid_dir.mkdir(exist_ok=True)
        
        # Check if yt-dlp found video formats
        has_video = False
        if meta.get('formats'):
            info(f'Downloading Instagram video: {uploader}')
            with tempfile.TemporaryDirectory(prefix='ig_') as tmp_dir:
                tmp_out = os.path.join(tmp_dir, 'video.mp4')
                dl_result = subprocess.run(
                    ['yt-dlp', '--no-playlist', '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                     '--merge-output-format', 'mp4', '-o', tmp_out, clean_url],
                    capture_output=True, timeout=300
                )
                if dl_result.returncode == 0 and os.path.exists(tmp_out):
                    shutil.move(tmp_out, str(vid_dir / 'video.mp4'))
                    media_count += 1
                    has_video = True

        # 4. Download Images (Slide/Carousel support)
        img_dir = post_dir / 'images'
        img_dir.mkdir(exist_ok=True)
        
        # Use yt-dlp thumbnails as a high-quality image source if not a video
        img_urls = []
        if not has_video:
            # yt-dlp 'requested_thumbnails' or 'thumbnails' often contains the slide images for IG
            if 'thumbnails' in meta:
                # Filter for high res
                img_urls = [t['url'] for t in meta['thumbnails'] if t.get('width', 0) > 400]
        
        # Fallback to Playwright captured images if yt-dlp found nothing
        if not img_urls and pw_meta.get('images'):
            img_urls = pw_meta['images']

        for i, img_url in enumerate(img_urls[:10]): # Limit to 10 images
            dest = img_dir / f'{i+1:02d}.jpg'
            self._download_file(img_url, dest)
            media_count += 1

        # 5. Download Thumbnail
        thumb_url = meta.get('thumbnail') or (img_urls[0] if img_urls else None)
        if thumb_url:
            thumb_dir = post_dir / 'thumbnails'
            thumb_dir.mkdir(exist_ok=True)
            self._download_file(thumb_url, thumb_dir / 'cover.jpg')

        # 6. Download Avatar
        avatar_url = pw_meta.get('avatar')
        if avatar_url:
            self._download_file(avatar_url, post_dir / 'avatar.jpg')

        # --- content.txt / content.md ---
        (post_dir / 'content.txt').write_text(description, encoding='utf-8')
        safe_description_md = re.sub(r'(?m)^#', r'\#', description)
        
        md_lines = [
            f'# Instagram Post by {uploader}',
            '',
            f'**作者**: {uploader}  ',
            f'**发布时间**: {date_str}  ',
            f'**来源**: {clean_url}  ',
            '',
        ]
        if (vid_dir / 'video.mp4').exists():
            md_lines.append('[视频](videos/video.mp4)\n')
        
        # Add images to markdown
        for f in sorted(img_dir.glob('*.jpg')):
            md_lines.append(f'![Image](images/{f.name})')
            
        md_lines.extend(['', '---', '', safe_description_md])
        (post_dir / 'content.md').write_text('\n'.join(md_lines), encoding='utf-8')

        # --- metadata.json ---
        metadata = {
            'id': video_id,
            'title': description[:100],
            'description': description,
            'uploader': uploader,
            'uploader_id': uploader_id,
            'url': clean_url,
            'platform': 'instagram',
            'saved_at': datetime.now().isoformat(),
            'avatar': avatar_url,
            'thumbnail': thumb_url,
            'media_count': media_count
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
            'media_count': media_count,
        }

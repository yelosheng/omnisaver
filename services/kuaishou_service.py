import asyncio
import json
import os
import re
import shutil
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from utils.realtime_logger import info, warning, success

class KuaishouServiceError(Exception):
    pass


class KuaishouService:
    """Kuaishou (快手) video downloader service using Playwright."""

    _URL_RE = re.compile(
        r'https?://(?:'
        r'(?:www\.)?kuaishou\.com/(?:short-video/|f/|video/)[\w-]+'
        r'|v\.kuaishou\.com/[\w-]+'
        r')'
    )

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir))
        self.base_path = Path(base_path) / 'saved_kuaishou'
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    @classmethod
    def is_valid_kuaishou_url(cls, url: str) -> bool:
        return bool(cls._URL_RE.search(url))

    @classmethod
    def extract_url_from_share_text(cls, text: str) -> str:
        """
        Extract a Kuaishou URL from a mobile share text blob.
        """
        m = cls._URL_RE.search(text)
        return m.group(0) if m else ''

    async def _fetch_metadata_async(self, url: str) -> dict:
        """Use Playwright to get Kuaishou metadata with request interception."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1',
                viewport={'width': 375, 'height': 812}
            )
            page = await context.new_page()
            
            # Intercept network requests to find real video URL
            captured_video_url = []
            async def handle_response(response):
                # Look for mp4 or video content types in common Kuaishou CDNs
                r_url = response.url
                if '.mp4' in r_url or 'video' in r_url:
                    if response.request.resource_type in ['media', 'fetch', 'xhr']:
                        captured_video_url.append(r_url)
            
            page.on('response', handle_response)
            
            info(f"Navigating to Kuaishou: {url}")
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                try:
                    await page.wait_for_selector('video', timeout=5000)
                except:
                    pass
            except Exception as e:
                warning(f"Kuaishou navigation timeout/error, continuing: {e}")

            await asyncio.sleep(2)

            # Try to extract data with zero special characters or backslashes
            meta = await page.evaluate('''() => {
                var v = document.querySelector('video');
                var a = document.querySelector('.user-info .name') || document.querySelector('.author-name');
                var d = document.querySelector('.desc-area .desc') || document.querySelector('.video-description');
                return {
                    video_src: v ? v.src : '',
                    poster: v ? v.poster : '',
                    author: a ? a.innerText.trim() : '',
                    desc: d ? d.innerText.trim() : '',
                    avatar: ''
                };
            }''')
            
            # Use intercepted URL if DOM src is missing or is a blob
            if (not meta.get('video_src') or meta.get('video_src').startswith('blob:')) and captured_video_url:
                meta['video_src'] = captured_video_url[0]
            
            await browser.close()
            return meta

    def _download_file(self, url: str, dest_path: Path):
        """Helper to download a file with urllib."""
        if not url: return
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1'}
        )
        with urllib.request.urlopen(req, timeout=60) as response, open(dest_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)

    def save_video(self, url: str) -> dict:
        """
        Download a Kuaishou video and save it locally.
        """
        if not self.is_valid_kuaishou_url(url):
            raise KuaishouServiceError(f'Invalid Kuaishou URL: {url}')

        # Run async metadata extraction
        try:
            meta = asyncio.run(self._fetch_metadata_async(url))
        except Exception as e:
            raise KuaishouServiceError(f"Playwright extraction failed: {e}")

        if not meta.get('video_src'):
            raise KuaishouServiceError("Could not find video source on the page.")

        video_src = meta['video_src']
        author_name = meta.get('author') or 'Kuaishou User'
        description = meta.get('desc') or 'No description'
        poster_url = meta.get('poster')
        avatar_url = meta.get('avatar')
        
        # Unique ID from video URL or original URL
        video_id_match = re.search(r'video/([\w-]+)', video_src) or re.search(r'video/([\w-]+)', url)
        video_id = video_id_match.group(1) if video_id_match else datetime.now().strftime('%H%M%S')

        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        
        # Directory creation
        safe_title = re.sub(r'[^\w\u4e00-\u9fff\- ]', '', description)[:40].strip() or 'kuaishou_video'
        folder_name = f'{date_str}_{safe_title}_{video_id}'
        if self.create_date_folders:
            post_dir = self.base_path / now.strftime('%Y-%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # 1. Download Video
        info(f'Downloading Kuaishou video: {author_name}')
        vid_dir = post_dir / 'videos'
        vid_dir.mkdir(exist_ok=True)
        video_file = vid_dir / 'video.mp4'
        try:
            self._download_file(video_src, video_file)
        except Exception as e:
            raise KuaishouServiceError(f"Video download failed: {e}")

        # 2. Download Thumbnail
        if poster_url:
            thumb_dir = post_dir / 'thumbnails'
            thumb_dir.mkdir(exist_ok=True)
            try:
                self._download_file(poster_url, thumb_dir / 'cover.jpg')
            except Exception as e:
                warning(f"Poster download failed: {e}")

        # 3. Download Avatar
        if avatar_url:
            try:
                self._download_file(avatar_url, post_dir / 'avatar.jpg')
            except Exception as e:
                warning(f"Avatar download failed: {e}")

        # --- content.txt ---
        (post_dir / 'content.txt').write_text(description, encoding='utf-8')

        # --- content.md ---
        safe_desc_md = re.sub(r'(?m)^#', r'\#', description)
        md = '\n'.join([
            f'# Kuaishou Video by {author_name}',
            '',
            f'**作者**: {author_name}  ',
            f'**发布时间**: {date_str}  ',
            f'**来源**: {url}  ',
            '',
            '[视频](videos/video.mp4)',
            '',
            '---',
            '',
            safe_desc_md,
        ])
        (post_dir / 'content.md').write_text(md, encoding='utf-8')

        # --- metadata.json ---
        metadata = {
            'id': video_id,
            'title': description[:100],
            'description': description,
            'uploader': author_name,
            'url': url,
            'platform': 'kuaishou',
            'saved_at': datetime.now().isoformat(),
            'video_url': video_src,
            'avatar': avatar_url
        }
        (post_dir / 'metadata.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        success(f'Kuaishou video saved to {post_dir}')
        return {
            'video_id': video_id,
            'title': description[:100],
            'save_path': str(post_dir),
            'author_username': author_name,
            'author_name': author_name,
            'tweet_text': description[:500],
            'media_count': 1,
        }

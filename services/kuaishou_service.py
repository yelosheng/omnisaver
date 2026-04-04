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
            # Switch to Desktop UA to support both mobile and desktop links
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800}
            )
            page = await context.new_page()
            
            # Intercept network requests to find real video URL
            captured_video_url = []
            async def handle_response(response):
                # Look for mp4 or video content types in common Kuaishou CDNs
                r_url = response.url
                if ('.mp4' in r_url or 'video' in r_url) and not r_url.startswith('blob:'):
                    if response.request.resource_type in ['media', 'fetch', 'xhr']:
                        captured_video_url.append(r_url)
            
            page.on('response', handle_response)
            
            info(f"Navigating to Kuaishou: {url}")
            try:
                # For desktop URLs, networkidle is more reliable to capture the stream
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                try:
                    await page.wait_for_selector('video', timeout=10000)
                except:
                    pass
            except Exception as e:
                warning(f"Kuaishou navigation timeout/error, continuing: {e}")

            await asyncio.sleep(3)

            # Try to extract data with zero special characters or backslashes
            meta = await page.evaluate('''() => {
                var v = document.querySelector('video');
                var video_src = v ? v.src : '';
                var poster = v ? v.poster : '';
                
                var author = '';
                var desc = '';
                var avatar = '';

                // Desktop site often has author in .user-name or similar
                var aEl = document.querySelector('.user-info .name, .author-name, .user-name, .nickname');
                if (aEl) author = aEl.innerText.trim();
                
                var dEl = document.querySelector('.desc-area .desc, .video-description, .video-info .info, .caption');
                if (dEl) desc = dEl.innerText.trim();

                // 1. Get all images to find avatar and poster if still empty
                var imgs = Array.from(document.querySelectorAll('img'));
                for (var i = 0; i < imgs.length; i++) {
                    var src = imgs[i].src;
                    if (!avatar && (src.indexOf('uhead') !== -1 || imgs[i].className.indexOf('avatar') !== -1)) avatar = src;
                    if (!poster && src.indexOf('upic') !== -1) poster = src;
                }

                // 2. Fallback parse body text for author and description
                if (!author) {
                    var bodyText = document.body.innerText;
                    var lines = bodyText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                    for (var j = 0; j < lines.length; j++) {
                        if (lines[j] === '@' && j + 1 < lines.length) {
                            author = lines[j+1];
                            if (!desc && j + 2 < lines.length) desc = lines[j+2];
                            break;
                        }
                    }
                }

                return {
                    video_src: video_src,
                    poster: poster,
                    author: author,
                    desc: desc,
                    avatar: avatar
                };
            }''')
            
            # Use intercepted URL if DOM src is missing or is a blob
            if (not meta.get('video_src') or meta.get('video_src').startswith('blob:')) and captured_video_url:
                meta['video_src'] = captured_video_url[0]
            
            await browser.close()
            return meta

    def _download_file(self, url: str, dest_path: Path):
        """Helper to download a file with urllib, adding Referer to bypass blocks."""
        if not url: return
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Referer': 'https://www.kuaishou.com/'
        }
        req = urllib.request.Request(url, headers=headers)
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

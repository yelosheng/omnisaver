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

class DouyinServiceError(Exception):
    pass


class DouyinService:
    """Douyin (抖音) and TikTok video downloader service using Playwright (replaces yt-dlp)."""

    _URL_RE = re.compile(
        r'https?://(?:'
        r'(?:www\.|m\.)?douyin\.com/video/\d+'
        r'|v\.douyin\.com/[\w/-]+'
        r'|(?:www\.)?tiktok\.com/@[^/]+/video/\d+'
        r'|vm\.tiktok\.com/[\w/-]+'
        r')'
    )

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir))
        self.base_path = Path(base_path) / 'saved_douyin'
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

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

    async def _fetch_metadata_async(self, url: str) -> dict:
        """Use Playwright to get Douyin metadata from window._ROUTER_DATA."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1',
                viewport={'width': 375, 'height': 812}
            )
            page = await context.new_page()
            
            try:
                await page.goto(url, wait_until='networkidle', timeout=30000)
            except Exception as e:
                # It might timeout but the DOM could still be loaded enough
                warning(f"Douyin navigation timeout/error, continuing anyway: {e}")

            # Grab all scripts to find _ROUTER_DATA
            script_contents = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('script')).map(s => s.textContent);
            }''')
            
            await browser.close()

            for content in script_contents:
                if content and 'window._ROUTER_DATA' in content:
                    match = re.search(r'window\._ROUTER_DATA\s*=\s*(.*)', content, re.DOTALL)
                    if match:
                        json_str = match.group(1).strip()
                        if json_str.endswith(';'):
                            json_str = json_str[:-1]
                        try:
                            data = json.loads(json_str)
                            return data
                        except json.JSONDecodeError as e:
                            raise DouyinServiceError(f"Failed to parse _ROUTER_DATA JSON: {e}")

            raise DouyinServiceError("Could not find _ROUTER_DATA on the page. Douyin page structure might have changed.")

    def _download_file(self, url: str, dest_path: Path):
        """Helper to download a file with urllib using a standard mobile user-agent."""
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1'}
        )
        with urllib.request.urlopen(req, timeout=60) as response, open(dest_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)

    def save_video(self, url: str) -> dict:
        """
        Download a Douyin/TikTok video and save it locally using Playwright.

        Directory layout:
          videos/video.mp4
          thumbnails/cover.jpg
          content.md
          content.txt
          metadata.json
        """
        if not self.is_valid_douyin_url(url):
            raise DouyinServiceError(f'Invalid Douyin/TikTok URL: {url}')

        info(f'Fetching Douyin/TikTok metadata via Playwright: {url}')

        # Run async metadata extraction
        try:
            raw_meta = asyncio.run(self._fetch_metadata_async(url))
        except Exception as e:
            raise DouyinServiceError(f"Playwright metadata extraction failed: {e}")

        item = None
        # Douyin has different formats, check common locations:
        
        # Format 1: videoInfoRes -> item_list
        try:
            item_list = raw_meta.get('loaderData', {}).get('video_(id)/page', {}).get('videoInfoRes', {}).get('item_list', [])
            if item_list and isinstance(item_list, list):
                item = item_list[0]
        except:
            pass

        # Fallback to scan recursively for itemStruct or item_list
        if not item:
            def find_item(d):
                if isinstance(d, dict):
                    if 'itemStruct' in d and isinstance(d['itemStruct'], dict):
                        return d['itemStruct']
                    if 'item_list' in d and isinstance(d['item_list'], list) and len(d['item_list']) > 0:
                        return d['item_list'][0]
                    for k, v in d.items():
                        res = find_item(v)
                        if res: return res
                elif isinstance(d, list):
                    for i in d:
                        res = find_item(i)
                        if res: return res
                return None
            item = find_item(raw_meta)

        if not item:
            raise DouyinServiceError("Could not locate video 'itemStruct' or 'item_list' inside the metadata.")

        # Extract needed fields
        video_id = str(item.get('aweme_id', ''))
        title = item.get('desc', 'untitled')
        title_safe = title[:60].strip() or 'untitled'
        author_info = item.get('author', {})
        uploader = author_info.get('nickname', '')
        uploader_id = author_info.get('unique_id') or author_info.get('uid', '')
        description = title

        # Creation time
        create_time_unix = item.get('create_time')
        pub_date = datetime.now()
        if create_time_unix:
            pub_date = datetime.fromtimestamp(create_time_unix)
        date_str = pub_date.strftime('%Y-%m-%d')
        
        # Duration
        duration_ms = item.get('video', {}).get('duration', 0)
        duration_s = duration_ms / 1000
        duration = f"{duration_s:.1f}s" if duration_ms else ""

        # Extract unwatermarked video URL
        play_addr = item.get('video', {}).get('playAddr', '')
        if not play_addr:
            play_addr = item.get('video', {}).get('play_addr', {}).get('url_list', [''])[0]
        
        if not play_addr:
            raise DouyinServiceError("Could not find video playback URL in metadata.")
        
        if 'playwm' in play_addr:
            play_addr = play_addr.replace('playwm', 'play')

        # Extract cover image
        cover_url = item.get('video', {}).get('cover', {}).get('url_list', [''])[0]

        # Directory creation
        safe_folder_title = re.sub(r'[^\w\u4e00-\u9fff\- ]', '', title_safe)[:40].strip()
        folder_name = f'{date_str}_{safe_folder_title}_{video_id}'
        if self.create_date_folders:
            post_dir = self.base_path / pub_date.strftime('%Y-%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # Download Video
        info(f'Downloading video: {title_safe}')
        vid_dir = post_dir / 'videos'
        vid_dir.mkdir(exist_ok=True)
        video_file = vid_dir / 'video.mp4'
        try:
            self._download_file(play_addr, video_file)
        except Exception as e:
            raise DouyinServiceError(f"Video download failed: {e}")

        # Download Thumbnail
        thumb_dir = post_dir / 'thumbnails'
        thumb_dir.mkdir(exist_ok=True)
        if cover_url:
            ext = 'jpg'
            if 'webp' in cover_url:
                ext = 'webp'
            cover_file = thumb_dir / f'cover.{ext}'
            try:
                self._download_file(cover_url, cover_file)
            except Exception as e:
                warning(f"Cover download failed: {e}")

        # --- content.txt ---
        (post_dir / 'content.txt').write_text(description, encoding='utf-8')

        # --- content.md ---
        # Escape hashtags at the start of lines to prevent them being treated as H1 headers
        safe_description = re.sub(r'(?m)^#', r'\#', description)
        safe_title_md = re.sub(r'^#', r'\#', title)

        md = '\n'.join([
            f'# {safe_title_md}',
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
            safe_description,
        ])
        (post_dir / 'content.md').write_text(md, encoding='utf-8')

        # --- metadata.json ---
        trimmed_meta = {
            'id': video_id,
            'title': title,
            'description': description,
            'upload_date': pub_date.strftime('%Y%m%d'),
            'uploader': uploader,
            'uploader_id': uploader_id,
            'duration': duration_ms,
            'duration_string': duration,
            'thumbnail': cover_url,
            'webpage_url': url,
            'platform': 'douyin',
            'saved_at': datetime.now().isoformat()
        }
        (post_dir / 'metadata.json').write_text(
            json.dumps(trimmed_meta, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        success(f'Douyin/TikTok video saved to {post_dir}')
        return {
            'video_id': video_id,
            'title': title_safe,
            'save_path': str(post_dir),
            'author_username': uploader_id,
            'author_name': uploader,
            'tweet_text': description[:500],
            'media_count': 1,
        }

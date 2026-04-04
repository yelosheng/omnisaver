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

class WeiboServiceError(Exception):
    pass


class WeiboService:
    """Weibo (微博) downloader service using Playwright."""

    _URL_RE = re.compile(
        r'https?://(?:www\.|m\.)?weibo\.(?:com|cn)/(?:u/\d+/|status/|[\d]+/)?[A-Za-z0-9]+'
    )

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir))
        self.base_path = Path(base_path) / 'saved_weibo'
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    @classmethod
    def is_valid_weibo_url(cls, url: str) -> bool:
        return bool(cls._URL_RE.search(url))

    async def _fetch_metadata_async(self, url: str) -> dict:
        """Use Playwright to get Weibo metadata."""
        # Convert to mobile URL if needed
        mid = url.rstrip('/').split('/')[-1]
        m_url = f'https://m.weibo.cn/status/{mid}'
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1',
                viewport={'width': 375, 'height': 812}
            )
            page = await context.new_page()
            
            info(f"Navigating to Weibo: {m_url}")
            try:
                await page.goto(m_url, wait_until='networkidle', timeout=30000)
            except Exception as e:
                warning(f"Weibo navigation timeout/error: {e}")

            # Wait a bit for possible redirects
            await asyncio.sleep(2)

            # Try to extract data from window.$render_data
            data = await page.evaluate('''() => {
                if (window.$render_data && window.$render_data.status) return window.$render_data.status;
                
                const scripts = Array.from(document.querySelectorAll('script'));
                for (let s of scripts) {
                    if (s.textContent.includes('render_data')) {
                        const match = s.textContent.match(/render_data\\s*=\\s*\\[(.*?)\\]\\[0\\]/s);
                        if (match) {
                            try { return JSON.parse(match[1]); } catch(e) {}
                        }
                    }
                }
                return null;
            }''')
            
            # If still nothing, check if there's an API call we can wait for or a different structure
            if not data:
                # Try to find 'config' variable which sometimes contains 'status'
                data = await page.evaluate('''() => {
                    if (window.config && window.config.status) return window.config.status;
                    return null;
                }''')

            await browser.close()
            
            if data:
                return data
            
            raise WeiboServiceError("Could not extract Weibo data from the page. It might be private or the page structure has changed.")

    def _download_file(self, url: str, dest_path: Path):
        """Helper to download a file with urllib."""
        req = urllib.request.Request(
            url, 
            headers={
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1',
                'Referer': 'https://m.weibo.cn/'
            }
        )
        with urllib.request.urlopen(req, timeout=60) as response, open(dest_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)

    def save_post(self, url: str) -> dict:
        """
        Download a Weibo post and save it locally.
        """
        if not self.is_valid_weibo_url(url):
            raise WeiboServiceError(f'Invalid Weibo URL: {url}')

        # Run async metadata extraction
        try:
            status = asyncio.run(self._fetch_metadata_async(url))
        except Exception as e:
            raise WeiboServiceError(f"Playwright extraction failed: {e}")

        # Extract fields
        mid = str(status.get('id', ''))
        text_html = status.get('text', '')
        # Clean HTML from text for description
        text_raw = re.sub(r'<[^>]+>', '', text_html)
        
        user = status.get('user', {})
        author_name = user.get('screen_name', 'Unknown')
        author_username = str(user.get('id', ''))
        avatar_url = user.get('profile_image_url', '')
        
        created_at_str = status.get('created_at', '')
        # created_at in m.weibo.cn can be "Mon Sep 01 12:00:00 +0800 2025" or relative like "10-01" or "1小时前"
        # We'll try to parse it or fallback to now
        try:
            # Format: "Sat Apr 04 09:00:00 +0800 2026"
            pub_date = datetime.strptime(created_at_str, '%a %b %d %H:%M:%S %z %Y')
        except:
            pub_date = datetime.now()
            
        date_str = pub_date.strftime('%Y-%m-%d')
        
        # Directory creation
        safe_title = re.sub(r'[^\w\u4e00-\u9fff\- ]', '', text_raw)[:40].strip() or 'weibo_post'
        folder_name = f'{date_str}_{safe_title}_{mid}'
        if self.create_date_folders:
            post_dir = self.base_path / pub_date.strftime('%Y-%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        media_count = 0
        
        # 1. Download Avatar
        if avatar_url:
            try:
                self._download_file(avatar_url, post_dir / 'avatar.jpg')
            except Exception as e:
                warning(f"Weibo avatar download failed: {e}")

        # 2. Download Images
        images_dir = post_dir / 'images'
        pics = status.get('pics', [])
        if pics:
            images_dir.mkdir(exist_ok=True)
            for i, pic in enumerate(pics):
                img_url = pic.get('large', {}).get('url') or pic.get('url', '')
                if img_url:
                    ext = img_url.split('.')[-1].split('?')[0] or 'jpg'
                    dest = images_dir / f'{i+1:02d}.{ext}'
                    try:
                        self._download_file(img_url, dest)
                        media_count += 1
                    except Exception as e:
                        warning(f"Weibo image {i+1} download failed: {e}")

        # 3. Download Video
        videos_dir = post_dir / 'videos'
        page_info = status.get('page_info', {})
        video_url = None
        if page_info.get('type') == 'video':
            video_url = page_info.get('media_info', {}).get('stream_url') or \
                        page_info.get('media_info', {}).get('mp4_hd_url') or \
                        page_info.get('media_info', {}).get('mp4_sd_url')
            
            if video_url:
                videos_dir.mkdir(exist_ok=True)
                video_file = videos_dir / 'video.mp4'
                try:
                    info(f"Downloading Weibo video: {video_url}")
                    self._download_file(video_url, video_file)
                    media_count += 1
                    
                    # Also save cover as thumbnail
                    cover_url = page_info.get('page_pic', {}).get('url')
                    if cover_url:
                        thumb_dir = post_dir / 'thumbnails'
                        thumb_dir.mkdir(exist_ok=True)
                        self._download_file(cover_url, thumb_dir / 'cover.jpg')
                except Exception as e:
                    warning(f"Weibo video download failed: {e}")

        # --- content.txt ---
        (post_dir / 'content.txt').write_text(text_raw, encoding='utf-8')

        # --- content.md ---
        # Escape hashtags
        safe_desc_md = re.sub(r'(?m)^#', r'\#', text_raw)
        
        md_lines = [
            f'# Weibo Post by {author_name}',
            '',
            f'**作者**: {author_name}  ',
            f'**发布时间**: {created_at_str}  ',
            f'**来源**: {url}  ',
            '',
            '---',
            '',
            safe_desc_md,
            '',
        ]
        
        if video_url:
            md_lines.append('[视频](videos/video.mp4)')
            md_lines.append('')
            
        if pics:
            md_lines.append('---')
            md_lines.append('**图片**:')
            for i, pic in enumerate(pics):
                img_url = pic.get('large', {}).get('url') or pic.get('url', '')
                ext = img_url.split('.')[-1].split('?')[0] or 'jpg'
                md_lines.append(f'![图片{i+1}](images/{i+1:02d}.{ext})')
        
        (post_dir / 'content.md').write_text('\n'.join(md_lines), encoding='utf-8')

        # --- metadata.json ---
        metadata = {
            'id': mid,
            'text': text_raw,
            'author': author_name,
            'author_id': author_username,
            'created_at': created_at_str,
            'url': url,
            'platform': 'weibo',
            'media_count': media_count,
            'saved_at': datetime.now().isoformat(),
            'raw_status': status # Keep raw for debugging
        }
        (post_dir / 'metadata.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        success(f'Weibo post saved to {post_dir}')
        return {
            'post_id': mid,
            'title': f"Weibo: {author_name}",
            'save_path': str(post_dir),
            'author_username': author_username,
            'author_name': author_name,
            'tweet_text': text_raw[:500],
            'media_count': media_count,
        }

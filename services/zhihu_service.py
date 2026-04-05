import asyncio
import html
import json
import os
import re
import shutil
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from utils.realtime_logger import info, success, warning, error
from services.config_manager import ConfigManager


class ZhihuServiceError(Exception):
    pass


class ZhihuService:
    """Zhihu (知乎) downloader service using Playwright."""

    # Matches https://www.zhihu.com/question/123/answer/456 or https://zhuanlan.zhihu.com/p/123
    _URL_RE = re.compile(
        r'https?://(?:www\.|zhuanlan\.)?zhihu\.com/(?:question/\d+/answer/\d+|p/\d+)'
    )

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        self.config = ConfigManager()
        if base_path is None:
            base_path = self.config.get_save_path()
        self.base_path = Path(base_path) / 'saved_zhihu'
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    @classmethod
    def is_valid_zhihu_url(cls, url: str) -> bool:
        return bool(cls._URL_RE.search(url))

    @classmethod
    def extract_url_from_share_text(cls, text: str) -> str:
        """
        Extract a Zhihu URL from a share text blob.
        Returns the first matched URL, or '' if none found.
        """
        m = cls._URL_RE.search(text)
        if m:
            return m.group(0)
        return ''

    def _get_cookies(self) -> list:
        """Load cookies from zhihu_cookies.json, falling back to z_c0 from config."""
        data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
        cookie_file = Path(data_dir) / 'zhihu_cookies.json'
        if cookie_file.exists():
            with open(cookie_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            # Convert Cookie-Editor format to Playwright format
            pw_cookies = []
            for c in raw:
                if 'name' not in c or 'value' not in c:
                    continue
                entry = {
                    'name': c['name'],
                    'value': c['value'],
                    'domain': c.get('domain', '.zhihu.com'),
                    'path': c.get('path', '/'),
                }
                pw_cookies.append(entry)
            return pw_cookies
        # Fallback: z_c0 only
        z_c0 = self.config.get_config('zhihu', 'z_c0', fallback=None)
        if z_c0:
            return [{'name': 'z_c0', 'value': z_c0, 'domain': '.zhihu.com', 'path': '/'}]
        return []

    async def _fetch_content_async(self, url: str) -> dict:
        """Use Playwright to get Zhihu page content and extract data."""
        cookies = self._get_cookies()
        if not cookies:
            raise ZhihuServiceError(
                "Zhihu cookies are not configured. "
                "Please configure them in the Settings page."
            )

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 900},
                extra_http_headers={
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Upgrade-Insecure-Requests': '1',
                }
            )

            # Remove webdriver fingerprint before any page load
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            """)

            await context.add_cookies(cookies)

            page = await context.new_page()

            # Block unnecessary resources to speed up and reduce detection
            await page.route("**/*", lambda route: route.continue_() if route.request.resource_type in ["document", "script", "xhr", "fetch"] else route.abort())

            info(f"Navigating to Zhihu: {url}")
            try:
                # Go to the url and wait for domcontentloaded
                response = await page.goto(url, wait_until='domcontentloaded', timeout=45000)
                if response and response.status in (403, 401):
                    raise ZhihuServiceError(f"Zhihu blocked the request (HTTP {response.status}). The cookie might be invalid or expired.")

                # Wait for the main content to appear
                await page.wait_for_selector('.RichContent-inner, .Post-RichText', timeout=15000)
            except ZhihuServiceError:
                raise  # Don't swallow real errors
            except Exception as e:
                warning(f"Zhihu navigation error or timeout waiting for content: {e}")
                title = await page.title()
                if "验证码" in title or "安全验证" in title:
                    raise ZhihuServiceError("Zhihu blocked the request with a captcha. Please refresh your cookie.")
                # We will still try to extract what we can

            # Extract title, author, and HTML content
            data = await page.evaluate('''() => {
                // Get title
                let title = document.title.replace(' - 知乎', '').trim();
                let titleEl = document.querySelector('.QuestionHeader-title, .Post-Title');
                if (titleEl) title = titleEl.innerText.trim();

                // Get author
                let author = 'Unknown';
                let authorEl = document.querySelector('.AuthorInfo-name, .UserLink-link');
                if (authorEl) author = authorEl.innerText.trim();

                // Get avatar
                let avatar = '';
                let avatarEl = document.querySelector('.AuthorInfo-avatar');
                if (avatarEl) avatar = avatarEl.src;

                // Get content
                let contentHtml = '';
                let contentEl = document.querySelector('.RichContent-inner, .Post-RichText');
                if (contentEl) {
                    contentHtml = contentEl.innerHTML;
                }

                return { title, author, avatar, html: contentHtml };
            }''')

            await browser.close()
            
            if not data.get('html'):
                raise ZhihuServiceError("Could not extract Zhihu content. The page might require a valid login cookie, or the structure has changed.")

            return data

    def _fetch_via_api(self, url: str) -> Optional[dict]:
        """
        Fetch content via Zhihu's internal JSON API.
        Uses curl_cffi to impersonate Chrome's TLS fingerprint (avoids SSLEOFError / 403).
        Returns a dict with keys: title, author, avatar, html — or None on failure.
        """
        cookies_list = self._get_cookies()
        if not cookies_list:
            return None
        cookie_dict = {c['name']: c['value'] for c in cookies_list}

        try:
            from curl_cffi import requests as req
            session = req.Session(impersonate="chrome124")
        except ImportError:
            warning("curl_cffi not installed, falling back to plain requests (may be blocked by TLS fingerprinting).")
            import requests as req
            session = req.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://www.zhihu.com/',
            'x-requested-with': 'fetch',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
        })
        session.cookies.update(cookie_dict)

        try:
            if 'answer/' in url:
                answer_id = url.split('answer/')[-1].split('/')[0].split('?')[0]
                question_id = url.split('question/')[-1].split('/')[0]
                api_url = (
                    f"https://www.zhihu.com/api/v4/answers/{answer_id}"
                    f"?include=content%2Cauthor%2Cvoteup_count%2Cis_normal%2Cis_copyable"
                )
                resp = session.get(api_url, timeout=30)
                info(f"Zhihu API response: HTTP {resp.status_code}")
                if resp.status_code != 200:
                    warning(f"Zhihu API returned {resp.status_code}, body: {resp.text[:200]}")
                    return None
                data = resp.json()
                content_html = data.get('content', '')
                author_name = data.get('author', {}).get('name', 'Unknown')
                avatar_url = data.get('author', {}).get('avatar_url', '')
                question_title = data.get('question', {}).get('title', '')
                if not question_title:
                    q_resp = session.get(
                        f"https://www.zhihu.com/api/v4/questions/{question_id}?include=title",
                        timeout=30
                    )
                    if q_resp.status_code == 200:
                        question_title = q_resp.json().get('title', '')
                return {'title': question_title, 'author': author_name, 'avatar': avatar_url, 'html': content_html}

            elif '/p/' in url:
                article_id = url.split('/p/')[-1].split('/')[0].split('?')[0]
                api_url = (
                    f"https://www.zhihu.com/api/v4/articles/{article_id}"
                    f"?include=content%2Cauthor%2Ctitle"
                )
                resp = session.get(api_url, timeout=30)
                info(f"Zhihu API response: HTTP {resp.status_code}")
                if resp.status_code != 200:
                    warning(f"Zhihu API returned {resp.status_code}, body: {resp.text[:200]}")
                    return None
                data = resp.json()
                return {
                    'title': data.get('title', ''),
                    'author': data.get('author', {}).get('name', 'Unknown'),
                    'avatar': data.get('author', {}).get('avatar_url', ''),
                    'html': data.get('content', ''),
                }
        except Exception as e:
            warning(f"Zhihu API fetch exception: {e}")
        return None

    def save_post(self, url: str) -> dict:
        """
        Download a Zhihu post and save it locally.
        """
        if not self.is_valid_zhihu_url(url):
            raise ZhihuServiceError(f'Invalid Zhihu URL: {url}')

        # Clean URL
        url = url.split('?')[0]

        # Try fast API approach first (avoids browser TLS fingerprint detection)
        info("Trying Zhihu JSON API...")
        data = self._fetch_via_api(url)
        if data and data.get('html'):
            info("Zhihu content fetched via API successfully.")
        else:
            # Fall back to Playwright browser
            warning("Zhihu API failed or returned empty, falling back to Playwright...")
            try:
                data = asyncio.run(self._fetch_content_async(url))
            except Exception as e:
                raise ZhihuServiceError(f"Zhihu extraction failed: {e}")

        title = data.get('title', 'Zhihu_Post').replace('/', '_').replace('\\', '_')
        author = data.get('author', 'Unknown')
        html_content = data.get('html', '')

        # Create folder
        now = datetime.now()
        safe_title = re.sub(r'[^\w\u4e00-\u9fa5]+', '_', title)[:30]
        
        # Extract ID from URL
        item_id = 'unknown'
        if 'answer/' in url:
            item_id = url.split('answer/')[-1].split('/')[0]
        elif '/p/' in url:
            item_id = url.split('/p/')[-1].split('/')[0]

        folder_name = f"{now.strftime('%Y-%m-%d')}_{safe_title}_{item_id}"
        
        if self.create_date_folders:
            month_folder = now.strftime('%Y-%m')
            post_dir = self.base_path / month_folder / folder_name
        else:
            post_dir = self.base_path / folder_name

        post_dir.mkdir(parents=True, exist_ok=True)
        
        info(f"Saving Zhihu post to: {post_dir}")

        # Save basic files
        # Convert HTML to MD
        from utils.html_to_markdown import TwitterHTMLToMarkdown  # local import avoids circular deps
        converter = TwitterHTMLToMarkdown()
        
        # Pre-process HTML to handle Zhihu's lazy-loaded images and math formulas
        html_content = re.sub(r'<img[^>]*data-actualsrc="([^"]+)"[^>]*>', r'<img src="\1">', html_content)
        html_content = re.sub(r'<img[^>]*data-original="([^"]+)"[^>]*>', r'<img src="\1">', html_content)
        
        # Handle math equations (ztext-math)
        html_content = re.sub(r'<span class="ztext-math"[^>]*data-tex="([^"]+)"[^>]*>.*?</span>', r'$\1$', html_content)
        
        md_text = converter.convert(html_content)

        # Download media
        img_urls = []
        for match in re.finditer(r'<img[^>]*src="([^"]+)"[^>]*>', html_content):
            src = match.group(1)
            if src.startswith('http') and 'data:image' not in src:
                # Remove resizing parameters to get original image
                src = src.replace('_b.', '.').replace('_r.', '.').replace('_hd.', '.').replace('_720w.', '.')
                if src not in img_urls:
                    img_urls.append(src)

        if img_urls:
            img_dir = post_dir / 'images'
            img_dir.mkdir(exist_ok=True)
            for i, img_url in enumerate(img_urls, 1):
                ext = img_url.split('.')[-1].split('?')[0]
                if ext.lower() not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    ext = 'jpg'
                local_path = f"images/{i:02d}.{ext}"
                dest = post_dir / local_path
                try:
                    req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, 'wb') as out:
                        shutil.copyfileobj(resp, out)
                    md_text = md_text.replace(img_url, local_path)
                    html_content = html_content.replace(img_url, local_path)
                except Exception as e:
                    warning(f"Failed to download image {img_url}: {e}")

        # Download avatar
        avatar_url = data.get('avatar')
        if avatar_url and avatar_url.startswith('http'):
            try:
                req = urllib.request.Request(avatar_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=30) as response, open(post_dir / 'avatar.jpg', 'wb') as f:
                    shutil.copyfileobj(response, f)
            except Exception as e:
                warning(f"Failed to download avatar: {e}")

        # Assemble metadata
        meta = {
            'platform': 'zhihu',
            'title': title,
            'author': author,
            'url': url,
            'saved_at': now.isoformat(),
            'item_id': item_id
        }
        
        # Write metadata
        with open(post_dir / 'metadata.json', 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
            
        # Write content.md
        md_full = f"# {title}\n\n**作者**: {author}\n**链接**: {url}\n\n---\n\n{md_text}"
        with open(post_dir / 'content.md', 'w', encoding='utf-8') as f:
            f.write(md_full)
            
        # Write content.txt
        text_clean = html.unescape(re.sub(r'<[^>]+>', '', html_content))
        with open(post_dir / 'content.txt', 'w', encoding='utf-8') as f:
            f.write(f"{title}\nAuthor: {author}\n\n{text_clean}")
            
        success(f"Successfully saved Zhihu post: {title}")

        return {
            'post_id': item_id,
            'title': title,
            'author_name': author,
            'author_username': author,
            'tweet_text': text_clean[:500],
            'media_count': len(img_urls),
            'save_path': str(post_dir),
        }

def process_zhihu(url: str, base_path: str, task_id: int) -> bool:
    """Entry point for the background task processor."""
    try:
        service = ZhihuService(base_path=base_path)
        service.save_post(url)
        return True
    except Exception as e:
        error(f"Failed to process Zhihu task {task_id}: {e}")
        return False

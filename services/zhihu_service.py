import asyncio
import ast
import html
import json
import os
import re
import shutil
import urllib.parse
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

    # Matches Zhihu answer/article/pin URLs such as:
    #   https://www.zhihu.com/question/123/answer/456
    #   https://www.zhihu.com/answer/456
    #   https://zhuanlan.zhihu.com/p/123
    #   https://www.zhihu.com/pin/123
    _URL_RE = re.compile(
        r'https?://(?:www\.|zhuanlan\.)?zhihu\.com/(?:question/\d+/answer/\d+|answer/\d+|p/\d+|pin/\d+)'
    )
    _ANY_ZHIHU_URL_RE = re.compile(r'https?://(?:www\.|zhuanlan\.)?zhihu\.com/[^\s]+')

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        self.config = ConfigManager()
        if base_path is None:
            base_path = self.config.get_save_path()
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    def _diagnostics_dir(self) -> Optional[Path]:
        if os.environ.get('ZHIHU_DEBUG_CAPTURE', '').lower() not in ('1', 'true', 'yes', 'on'):
            return None
        data_dir = Path(os.environ.get('DATA_DIR', str(Path(__file__).parent.parent)))
        out_dir = data_dir / 'diagnostics' / 'zhihu'
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    @staticmethod
    def _url_debug_slug(url: str) -> str:
        return re.sub(r'[^a-zA-Z0-9]+', '_', url).strip('_')[:80] or 'zhihu'

    @classmethod
    def is_valid_zhihu_url(cls, url: str) -> bool:
        return bool(cls.classify_zhihu_url(url))

    @classmethod
    def normalize_zhihu_url(cls, url: str) -> str:
        if not url:
            return ''
        cleaned = url.strip()
        m = cls._ANY_ZHIHU_URL_RE.search(cleaned)
        if m:
            cleaned = m.group(0)
        cleaned = cleaned.replace('&amp;', '&')
        cleaned = cleaned.split('#', 1)[0]
        parsed = urllib.parse.urlsplit(cleaned)
        if not parsed.scheme or not parsed.netloc:
            return cleaned

        keep_params = []
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False):
            lowered = key.lower()
            if lowered.startswith('utm_'):
                continue
            if lowered in {'native', 'scene', 'share_code', 'share_id', 'share_source', 'share_channel', 'share_from', 'mid', 'enter_from'}:
                continue
            keep_params.append((key, value))

        normalized_query = urllib.parse.urlencode(keep_params, doseq=True)
        normalized_path = re.sub(r'/+$', '', parsed.path) or '/'
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, normalized_path, normalized_query, ''))

    @classmethod
    def classify_zhihu_url(cls, url: str) -> str:
        normalized = cls.normalize_zhihu_url(url)
        if not normalized:
            return ''
        if re.search(r'https?://www\.zhihu\.com/question/\d+/answer/\d+', normalized):
            return 'answer'
        if re.search(r'https?://www\.zhihu\.com/answer/\d+', normalized):
            return 'answer'
        if re.search(r'https?://zhuanlan\.zhihu\.com/p/\d+', normalized):
            return 'article'
        if re.search(r'https?://www\.zhihu\.com/pin/\d+', normalized):
            return 'pin'
        return ''

    @classmethod
    def extract_url_from_share_text(cls, text: str) -> str:
        """
        Extract a Zhihu URL from a share text blob.
        Returns the first matched URL, or '' if none found.
        """
        m = cls._ANY_ZHIHU_URL_RE.search(text)
        if m:
            normalized = cls.normalize_zhihu_url(m.group(0))
            if cls.classify_zhihu_url(normalized):
                return normalized
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

    def _make_http_session(self, include_cookies: bool = True):
        """Create an HTTP session that mimics a normal browser as closely as possible."""
        cookie_dict = {}
        if include_cookies:
            cookies_list = self._get_cookies()
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
        if cookie_dict:
            session.cookies.update(cookie_dict)
        return session

    def _download_binary(self, session, asset_url: str, dest: Path, *, referer: str) -> None:
        """Download a binary asset with browser-like headers and basic retry."""
        headers = {
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Referer': referer,
            'sec-fetch-dest': 'image',
            'sec-fetch-mode': 'no-cors',
            'sec-fetch-site': 'cross-site',
        }

        last_error = None
        for _ in range(2):
            try:
                resp = session.get(asset_url, headers=headers, timeout=30)
                if resp.status_code != 200:
                    raise ZhihuServiceError(f'HTTP {resp.status_code}')
                dest.write_bytes(resp.content)
                return
            except Exception as e:
                last_error = e
        raise ZhihuServiceError(f'Failed to download asset: {last_error}')

    @staticmethod
    def _normalize_pin_title(title: str, fallback: str = 'Zhihu_Pin') -> str:
        raw = html.unescape(str(title or '')).strip()
        if not raw:
            return fallback
        raw = raw.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
        raw = re.sub(r'<[^>]+>', '', raw)
        raw = raw.strip()
        if not raw:
            return fallback
        return raw.splitlines()[0].strip() or fallback

    @classmethod
    def _render_pin_blocks_to_html(cls, blocks) -> str:
        if not blocks:
            return ''
        if isinstance(blocks, str):
            stripped = blocks.strip()
            if not stripped:
                return ''
            if stripped.startswith('<'):
                return stripped
            parsed = None
            for loader in (json.loads, ast.literal_eval):
                try:
                    parsed = loader(stripped)
                    break
                except Exception:
                    continue
            if parsed is not None:
                blocks = parsed
            else:
                escaped = html.escape(stripped).replace('\n', '<br>')
                return f'<p>{escaped}</p>'

        if isinstance(blocks, dict):
            blocks = [blocks]

        html_parts = []
        for block in blocks:
            if not isinstance(block, dict):
                text = html.escape(str(block)).strip()
                if text:
                    html_parts.append(f'<p>{text}</p>')
                continue

            block_type = str(block.get('type', '')).lower()
            text_value = block.get('own_text') or block.get('content') or block.get('title') or ''
            if block_type == 'image':
                src = block.get('original_url') or block.get('url') or block.get('watermark_url') or block.get('thumbnail') or ''
                if src:
                    html_parts.append(f'<figure><img src="{src}"></figure>')
                continue

            if isinstance(text_value, str) and text_value.strip():
                escaped = html.unescape(text_value).replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
                paragraphs = [p.strip() for p in escaped.split('\n') if p.strip()]
                if paragraphs:
                    for paragraph in paragraphs:
                        html_parts.append(f'<p>{paragraph}</p>')
                    continue

            src = block.get('original_url') or block.get('url')
            if src:
                html_parts.append(f'<figure><img src="{src}"></figure>')

        return ''.join(html_parts)

    async def _fetch_content_async(self, url: str, include_cookies: bool = True) -> dict:
        """Use Playwright to get Zhihu page content and extract data."""
        cookies = self._get_cookies() if include_cookies else []
        if include_cookies and not cookies:
            raise ZhihuServiceError(
                "Zhihu cookies are not configured. "
                "Please configure them in the Settings page."
            )
        is_article = '/p/' in url
        is_pin = '/pin/' in url
        site_origin = 'https://zhuanlan.zhihu.com' if is_article else 'https://www.zhihu.com'
        site_home = f'{site_origin}/'
        diagnostics_dir = self._diagnostics_dir()
        debug_slug = self._url_debug_slug(url)
        capture_mode = 'cookies' if include_cookies else 'nocookies'
        context_kwargs = {
            'user_agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            'viewport': {'width': 1280, 'height': 900},
            'locale': 'zh-CN',
            'extra_http_headers': {
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Referer': site_home,
                'Origin': site_origin,
                'Upgrade-Insecure-Requests': '1',
            }
        }
        if diagnostics_dir:
            context_kwargs['record_har_path'] = str(diagnostics_dir / f'{debug_slug}_{capture_mode}.har')
            context_kwargs['record_har_mode'] = 'full'

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                ]
            )
            context = await browser.new_context(**context_kwargs)
            if diagnostics_dir:
                har_path = diagnostics_dir / f'{debug_slug}_{capture_mode}.har'
                await context.tracing.start(screenshots=True, snapshots=True)
                info(f"Zhihu debug capture enabled: HAR/traces will be written under {diagnostics_dir}")

            # Remove webdriver fingerprint before any page load
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            """)

            if cookies:
                await context.add_cookies(cookies)

            page = await context.new_page()
            await page.set_extra_http_headers({
                'Referer': site_home,
                'Origin': site_origin,
            })

            info(f"Navigating to Zhihu: {url}")
            try:
                # Warm up first-party context before opening the target page.
                warmup_response = await page.goto(site_home, wait_until='domcontentloaded', timeout=30000)
                if warmup_response and warmup_response.status in (403, 401) and is_article:
                    warning(f"Zhihu warmup returned HTTP {warmup_response.status} for {site_home}")

                # Go to the url and wait for the page to finish loading normally.
                response = await page.goto(url, wait_until='networkidle', timeout=45000)
                status_blocked = bool(response and response.status in (403, 401))
                if status_blocked:
                    warning(f"Zhihu returned HTTP {response.status} for {url}, checking whether article content is still present.")

                # Wait for the main content to appear
                try:
                    await page.wait_for_selector('.RichContent-inner, .Post-RichText, article', timeout=15000)
                except Exception:
                    if status_blocked:
                        raise ZhihuServiceError(f"Zhihu blocked the request (HTTP {response.status}).")
                    raise
            except ZhihuServiceError:
                if diagnostics_dir:
                    try:
                        await page.screenshot(path=str(diagnostics_dir / f'{debug_slug}_{capture_mode}_http_error.png'), full_page=True)
                        (diagnostics_dir / f'{debug_slug}_{capture_mode}_http_error.html').write_text(await page.content(), encoding='utf-8')
                    except Exception as capture_error:
                        warning(f"Zhihu debug capture failed after HTTP error: {capture_error}")
                raise  # Don't swallow real errors
            except Exception as e:
                warning(f"Zhihu navigation error or timeout waiting for content: {e}")
                title = await page.title()
                if "验证码" in title or "安全验证" in title:
                    if diagnostics_dir:
                        try:
                            await page.screenshot(path=str(diagnostics_dir / f'{debug_slug}_{capture_mode}_captcha.png'), full_page=True)
                            (diagnostics_dir / f'{debug_slug}_{capture_mode}_captcha.html').write_text(await page.content(), encoding='utf-8')
                        except Exception as capture_error:
                            warning(f"Zhihu debug capture failed after captcha: {capture_error}")
                    raise ZhihuServiceError("Zhihu blocked the request with a captcha. Please refresh your cookie.")
                # We will still try to extract what we can

            # Extract title, author, and HTML content
            data = await page.evaluate('''() => {
                // Get title
                let title = document.title.replace(' - 知乎', '').trim();
                let titleEl = document.querySelector('.QuestionHeader-title, .Post-Title, .PinItem-title, .ContentItem-title');
                if (titleEl) title = titleEl.innerText.trim();

                // Get author
                let author = 'Unknown';
                let authorEl = document.querySelector('.AuthorInfo-name, .UserLink-link, .PinItem-authorName');
                if (authorEl) author = authorEl.innerText.trim();

                // Get avatar
                let avatar = '';
                let avatarEl = document.querySelector('.AuthorInfo-avatar, .Avatar img, .PinItem-authorAvatar img');
                if (avatarEl) avatar = avatarEl.src;

                // Get content
                let contentHtml = '';
                let contentEl = document.querySelector('.RichContent-inner, .Post-RichText, .RichText.ztext, .PinItem, article');
                if (contentEl) {
                    contentHtml = contentEl.innerHTML;
                } else {
                    let stateEl = document.getElementById('js-initialData');
                    if (stateEl && stateEl.textContent) {
                        try {
                            let state = JSON.parse(stateEl.textContent);
                            let articleIdMatch = window.location.pathname.match(/\\/p\\/(\\d+)/);
                            let articleId = articleIdMatch ? articleIdMatch[1] : '';
                            let articleData = articleId && state.initialState && state.initialState.entities &&
                                state.initialState.entities.articles && state.initialState.entities.articles[articleId];
                            if (articleData) {
                                let articleAuthor = articleData.author || {};
                                title = articleData.title || title;
                                author = articleAuthor.name || articleAuthor.fullName || author;
                                avatar = articleAuthor.avatarUrl || articleAuthor.avatarUrlTemplate || articleAuthor.avatar_url || avatar;
                                contentHtml = articleData.content || '';
                            }
                            let pinIdMatch = window.location.pathname.match(/\\/pin\\/(\\d+)/);
                            let pinId = pinIdMatch ? pinIdMatch[1] : '';
                            let pinData = pinId && state.initialState && state.initialState.entities &&
                                state.initialState.entities.pins && state.initialState.entities.pins[pinId];
                            if (pinData) {
                                let pinAuthor = pinData.author || {};
                                title = pinData.title || pinData.excerptTitle || title || 'Zhihu Pin';
                                author = pinAuthor.name || pinAuthor.fullName || author;
                                avatar = pinAuthor.avatarUrl || pinAuthor.avatarUrlTemplate || pinAuthor.avatar_url || avatar;
                                contentHtml = pinData.content || pinData.richText || pinData.detail || contentHtml;
                                if (!contentHtml && pinData.excerptTitle) {
                                    contentHtml = `<p>${pinData.excerptTitle}</p>`;
                                }
                                if ((!contentHtml || contentHtml === '<p></p>') && Array.isArray(pinData.images) && pinData.images.length) {
                                    contentHtml = pinData.images.map((img) => {
                                        let src = img.originalUrl || img.url || img.thumbnail || '';
                                        return src ? `<figure><img src="${src}"></figure>` : '';
                                    }).join('');
                                }
                            }
                        } catch (e) {}
                    }
                }

                if (!author || author === 'Unknown') {
                    try {
                        let pageHtml = document.documentElement.innerHTML || '';
                        let shareTextMatch = pageHtml.match(/作者[:：]\\s*([^\\s<"\\\\]+)/);
                        if (shareTextMatch && shareTextMatch[1]) {
                            author = shareTextMatch[1];
                        }
                    } catch (e) {}
                }

                return { title, author, avatar, html: contentHtml };
            }''')

            if diagnostics_dir:
                try:
                    await page.screenshot(path=str(diagnostics_dir / f'{debug_slug}_{capture_mode}_final.png'), full_page=True)
                    (diagnostics_dir / f'{debug_slug}_{capture_mode}_final.html').write_text(await page.content(), encoding='utf-8')
                    await context.tracing.stop(path=str(diagnostics_dir / f'{debug_slug}_{capture_mode}_trace.zip'))
                except Exception as capture_error:
                    warning(f"Zhihu debug capture finalization failed: {capture_error}")

            await context.close()
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
        session = self._make_http_session()

        try:
            if 'answer/' in url:
                answer_id = url.split('answer/')[-1].split('/')[0].split('?')[0]
                question_id = None
                if 'question/' in url:
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
                if not question_title and question_id:
                    q_resp = session.get(
                        f"https://www.zhihu.com/api/v4/questions/{question_id}?include=title",
                        timeout=30
                    )
                    if q_resp.status_code == 200:
                        question_title = q_resp.json().get('title', '')
                return {'title': question_title, 'author': author_name, 'avatar': avatar_url, 'html': content_html}

            elif '/p/' in url:
                article_id = url.split('/p/')[-1].split('/')[0].split('?')[0]
                article_attempts = [
                    (
                        session,
                        f"https://www.zhihu.com/api/v4/articles/{article_id}?include=content%2Cauthor%2Ctitle",
                    ),
                    (
                        self._make_http_session(include_cookies=False),
                        f"https://zhuanlan.zhihu.com/api/articles/{article_id}",
                    ),
                ]
                for article_session, api_url in article_attempts:
                    resp = article_session.get(api_url, timeout=30)
                    info(f"Zhihu API response: HTTP {resp.status_code}")
                    if resp.status_code != 200:
                        warning(f"Zhihu API returned {resp.status_code}, body: {resp.text[:200]}")
                        continue
                    data = resp.json()
                    return {
                        'title': data.get('title', ''),
                        'author': data.get('author', {}).get('name', 'Unknown'),
                        'avatar': data.get('author', {}).get('avatar_url', ''),
                        'html': data.get('content', ''),
                    }

            elif '/pin/' in url:
                pin_id = url.split('/pin/')[-1].split('/')[0].split('?')[0]
                api_url = (
                    f"https://www.zhihu.com/api/v4/pins/{pin_id}"
                    f"?include=content%2Cauthor"
                )
                resp = session.get(api_url, timeout=30)
                info(f"Zhihu API response: HTTP {resp.status_code}")
                if resp.status_code != 200:
                    warning(f"Zhihu API returned {resp.status_code}, body: {resp.text[:200]}")
                    return None
                data = resp.json()
                content_html = self._render_pin_blocks_to_html(data.get('content'))
                if not content_html:
                    content_html = self._render_pin_blocks_to_html(data.get('excerpt_title'))
                if not content_html:
                    image_blocks = []
                    for image in data.get('images', []) or []:
                        image_blocks.append({
                            'type': 'image',
                            'original_url': image.get('original_url'),
                            'url': image.get('url'),
                            'thumbnail': image.get('thumbnail'),
                        })
                    content_html = self._render_pin_blocks_to_html(image_blocks)
                return {
                    'title': self._normalize_pin_title(data.get('excerpt_title') or data.get('content') or 'Zhihu_Pin'),
                    'author': data.get('author', {}).get('name', 'Unknown'),
                    'avatar': data.get('author', {}).get('avatar_url', ''),
                    'html': content_html,
                }
        except Exception as e:
            warning(f"Zhihu API fetch exception: {e}")
        return None

    def save_post(self, url: str) -> dict:
        """
        Download a Zhihu post and save it locally.
        """
        url = self.normalize_zhihu_url(url)
        zhihu_type = self.classify_zhihu_url(url)
        if not zhihu_type:
            raise ZhihuServiceError(f'Invalid Zhihu URL: {url}')

        # Try fast API approach first (avoids browser TLS fingerprint detection)
        info("Trying Zhihu JSON API...")
        data = self._fetch_via_api(url)
        if data and data.get('html'):
            info("Zhihu content fetched via API successfully.")
        else:
            # Fall back to Playwright browser
            warning("Zhihu API failed or returned empty, falling back to Playwright...")
            try:
                try:
                    data = asyncio.run(self._fetch_content_async(url))
                except ZhihuServiceError as e:
                    if '/p/' in url and 'HTTP 403' in str(e):
                        warning("Zhihu article blocked with cookies, retrying Playwright without cookies...")
                        try:
                            data = asyncio.run(self._fetch_content_async(url, include_cookies=False))
                        except ZhihuServiceError as retry_error:
                            raise ZhihuServiceError(
                                "Zhihu article extraction failed after both cookie and no-cookie attempts. "
                                "This usually means the article/API is blocked for this environment or requires a different client path."
                            ) from retry_error
                    else:
                        raise
            except Exception as e:
                raise ZhihuServiceError(f"Zhihu extraction failed: {e}")

        title = data.get('title', 'Zhihu_Post').replace('/', '_').replace('\\', '_')
        author = data.get('author', 'Unknown')
        html_content = data.get('html', '')
        if '/pin/' in url:
            title = self._normalize_pin_title(title, fallback='Zhihu_Pin').replace('/', '_').replace('\\', '_')
            html_content = self._render_pin_blocks_to_html(html_content)

        # Create folder
        now = datetime.now()
        safe_title = re.sub(r'[^\w\u4e00-\u9fa5]+', '_', title)[:30]
        
        # Extract ID from URL
        item_id = 'unknown'
        if 'answer/' in url:
            item_id = url.split('answer/')[-1].split('/')[0]
        elif '/p/' in url:
            item_id = url.split('/p/')[-1].split('/')[0]
        elif '/pin/' in url:
            item_id = url.split('/pin/')[-1].split('/')[0]

        folder_name = f"{now.strftime('%Y-%m-%d')}_{safe_title}_{item_id}"
        
        if self.create_date_folders:
            post_dir = self.base_path / now.strftime('%Y') / now.strftime('%m') / folder_name
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

        # Download media
        image_refs = []
        for match in re.finditer(r'<img[^>]*src="([^"]+)"[^>]*>', html_content):
            original_src = match.group(1)
            if original_src.startswith('http') and 'data:image' not in original_src:
                normalized_src = original_src.replace('_b.', '.').replace('_r.', '.').replace('_hd.', '.').replace('_720w.', '.')
                image_refs.append((original_src, normalized_src))

        successful_images = {}
        if image_refs:
            img_dir = post_dir / 'images'
            img_dir.mkdir(exist_ok=True)
            session = self._make_http_session()
            unique_img_urls = []
            for _, normalized_src in image_refs:
                if normalized_src not in unique_img_urls:
                    unique_img_urls.append(normalized_src)

            for i, img_url in enumerate(unique_img_urls, 1):
                ext = img_url.split('.')[-1].split('?')[0]
                if ext.lower() not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    ext = 'jpg'
                local_path = f"images/{i:02d}.{ext}"
                dest = post_dir / local_path
                try:
                    self._download_binary(session, img_url, dest, referer=url)
                    successful_images[img_url] = local_path
                except Exception as e:
                    warning(f"Failed to download image {img_url}: {e}")

        for original_src, normalized_src in image_refs:
            local_path = successful_images.get(normalized_src)
            if local_path:
                html_content = html_content.replace(original_src, local_path)
                html_content = html_content.replace(normalized_src, local_path)

        md_text = converter.convert(html_content)

        # Download avatar
        avatar_url = data.get('avatar')
        if avatar_url and avatar_url.startswith('http'):
            try:
                session = self._make_http_session()
                self._download_binary(session, avatar_url, post_dir / 'avatar.jpg', referer=url)
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
            'media_count': len(successful_images),
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

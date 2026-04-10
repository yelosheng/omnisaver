"""
Feishu (飞书/Lark) document archiver.
Supports public wiki/docx/docs pages. Private pages require cookie auth (TODO).

Approach: Playwright renders the page, content container HTML is extracted,
markdownify converts to Markdown, embedded images are downloaded locally.
"""
import asyncio
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from utils.realtime_logger import info, success, warning, error


class FeishuServiceError(Exception):
    pass


class FeishuService:
    """Feishu/Lark public document archiver."""

    # Matches:
    #   https://<workspace>.feishu.cn/wiki/<id>
    #   https://<workspace>.feishu.cn/docx/<id>
    #   https://<workspace>.feishu.cn/docs/<id>
    #   https://<workspace>.larksuite.com/wiki/<id>   (international)
    _URL_RE = re.compile(
        r'https?://[a-zA-Z0-9-]+\.(?:feishu\.cn|larksuite\.com)/(?:wiki|docx|docs)/([a-zA-Z0-9_-]+)'
    )

    # TODO: load cookies for private docs
    _COOKIES_PATH = os.path.expanduser('~/.config/feishu/cookies.json')

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir) / 'saved_tweets')
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    @classmethod
    def is_valid_feishu_url(cls, url: str) -> bool:
        """Return True if url is a supported Feishu/Lark document URL."""
        return bool(cls._URL_RE.search(url.strip()))

    @classmethod
    def extract_doc_id(cls, url: str) -> str:
        """Extract document ID (last path segment) from URL."""
        m = cls._URL_RE.search(url.strip())
        return m.group(1) if m else hashlib.md5(url.encode()).hexdigest()[:12]

    def save_doc(self, url: str) -> dict:
        """
        Fetch a public Feishu document and save it locally.

        Files saved in post_dir:
            content.md      — Markdown with headings, code blocks, images
            content.html    — Raw extracted HTML (backup)
            metadata.json   — title, doc_id, source_url, saved_at
            images/         — Downloaded embedded images

        Returns dict with keys: doc_id, title, author_name, author_username,
                                  save_path, tweet_text, media_count
        """
        url = url.strip()
        doc_id = self.extract_doc_id(url)
        info(f'[FeishuService] Fetching: {url}')

        result = asyncio.run(self._async_fetch(url))
        if not result:
            raise FeishuServiceError(f'Failed to extract content from: {url}')

        title = result['title'] or 'Untitled'
        content_html = result['content_html']
        author = result.get('author', '')

        # Build save directory
        save_time = datetime.now()
        safe_title = re.sub(r'[^\w\u4e00-\u9fa5]+', '_', title)[:40].strip('_')
        folder_name = f'{save_time.strftime("%Y-%m-%d")}_{safe_title}_{doc_id}'
        if self.create_date_folders:
            post_dir = (self.base_path
                        / save_time.strftime('%Y')
                        / save_time.strftime('%m')
                        / folder_name)
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # Download images, replace src with local paths
        content_html, image_count = self._download_images(content_html, post_dir, url)

        # Save raw HTML
        (post_dir / 'content.html').write_text(content_html, encoding='utf-8')

        # Convert to Markdown
        md_body = self._to_markdown(content_html)
        header = '\n'.join([
            f'# {re.sub(r"^#", r"\\#", title)}',
            '',
            f'**Source**: {url}  ',
            f'**Saved**: {save_time.strftime("%Y-%m-%d %H:%M")}  ',
            '',
            '---',
            '',
            '',
        ])
        (post_dir / 'content.md').write_text(header + md_body, encoding='utf-8')

        # metadata.json
        metadata = {
            'doc_id': doc_id,
            'title': title,
            'author': author,
            'source_url': url,
            'image_count': image_count,
            'saved_at': save_time.isoformat(),
        }
        (post_dir / 'metadata.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        tweet_text = re.sub(r'\s+', ' ', md_body)[:500]
        success(f'[FeishuService] Saved "{title}" → {post_dir}')
        return {
            'doc_id': doc_id,
            'title': title,
            'author_name': author or 'Feishu',
            'author_username': urllib.parse.urlparse(url).netloc,
            'save_path': str(post_dir),
            'tweet_text': tweet_text,
            'media_count': image_count,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _async_fetch(self, url: str) -> dict | None:
        """Render page with Playwright, return {title, content_html, author}."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise FeishuServiceError('playwright is not installed')

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
                      '--disable-blink-features=AutomationControlled'],
            )
            context = await browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1440, 'height': 900},
                locale='zh-CN',
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until='networkidle', timeout=45000)

                # Wait for Feishu's content to hydrate
                for selector in [
                    '.page-block-children',
                    '[data-block-type]',
                    '.docs-reader',
                    'article',
                ]:
                    try:
                        await page.wait_for_selector(selector, timeout=8000)
                        break
                    except Exception:
                        continue

                # Scroll to trigger lazy images
                await page.evaluate("""
                    async () => {
                        await new Promise(resolve => {
                            let y = 0;
                            const step = 500;
                            const timer = setInterval(() => {
                                window.scrollBy(0, step);
                                y += step;
                                if (y >= document.body.scrollHeight) {
                                    clearInterval(timer);
                                    window.scrollTo(0, 0);
                                    resolve();
                                }
                            }, 150);
                        });
                    }
                """)
                await page.wait_for_timeout(1500)

                title = await page.title()
                # Strip common Feishu title suffixes like " - Feishu Wiki"
                title = re.sub(r'\s*[-|–]\s*(飞书|Feishu|Lark).*$', '', title, flags=re.IGNORECASE).strip()

                # Extract main content container
                content_html = await page.evaluate("""
                    () => {
                        // Try Feishu-specific selectors in order of preference
                        const selectors = [
                            '.page-block-children',
                            '.docs-reader-content',
                            '[class*="reader-content"]',
                            '[class*="doc-content"]',
                            'article',
                            'main',
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.innerText.trim().length > 100) {
                                return el.innerHTML;
                            }
                        }
                        return document.body.innerHTML;
                    }
                """)

                return {'title': title, 'content_html': content_html or '', 'author': ''}

            except Exception as e:
                warning(f'[FeishuService] Fetch error: {e}')
                return None
            finally:
                await context.close()
                await browser.close()

    def _to_markdown(self, html: str) -> str:
        """Convert HTML to Markdown using markdownify."""
        try:
            import markdownify
        except ImportError:
            raise FeishuServiceError('markdownify is not installed. Run: pip install markdownify')

        md = markdownify.markdownify(
            html,
            heading_style='ATX',          # # style headings
            bullets='-',                   # consistent list bullets
            code_language_callback=self._detect_code_language,
            newline_style='backslash',
        )
        # Clean up excessive blank lines
        md = re.sub(r'\n{4,}', '\n\n\n', md)
        return md.strip()

    @staticmethod
    def _detect_code_language(el) -> str:
        """Extract language hint from Feishu code block class attributes."""
        classes = el.get('class', [])
        if isinstance(classes, str):
            classes = classes.split()
        for cls in classes:
            if cls.startswith('language-'):
                return cls[len('language-'):]
        # Check data-language attribute (Feishu uses this)
        lang = el.get('data-language', '') or el.get('data-lang', '')
        return lang.lower() if lang else ''

    def _download_images(self, html: str, post_dir: Path, base_url: str) -> tuple[str, int]:
        """
        Download all <img src="..."> images to post_dir/images/.
        Replace original src with relative local path.
        Returns (modified_html, image_count).
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        images_dir = post_dir / 'images'
        count = 0

        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or ''
            if not src or src.startswith('data:'):
                continue
            if not src.startswith('http'):
                src = urllib.parse.urljoin(base_url, src)

            ext = Path(urllib.parse.urlparse(src).path).suffix or '.jpg'
            ext = ext[:5]  # guard against very long extensions
            img_hash = hashlib.md5(src.encode()).hexdigest()[:10]
            filename = f'img_{count:03d}_{img_hash}{ext}'

            try:
                images_dir.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(src, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    (images_dir / filename).write_bytes(resp.read())
                img['src'] = f'images/{filename}'
                img.attrs.pop('data-src', None)
                count += 1
            except Exception as exc:
                warning(f'[FeishuService] Image download failed ({src}): {exc}')

        return str(soup), count

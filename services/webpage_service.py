"""
Pocket-style read-later service for arbitrary web pages.
Uses Playwright to render the page, then runs Mozilla's Readability.js
(the same algorithm as Firefox Reader Mode) in the browser context.
trafilatura handles metadata and plain-text output.
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

from utils.realtime_logger import info, warning, success


class WebpageServiceError(Exception):
    pass


# Path to bundled Readability.js (Mozilla, same as Firefox Reader Mode)
_READABILITY_JS = Path(__file__).parent / 'Readability.js'


class WebpageService:
    """Fetch any web page and save its main content for offline reading."""

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir) / 'saved_tweets')
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    @staticmethod
    def is_valid_webpage_url(url: str) -> bool:
        return bool(re.match(r'https?://', url.strip()))

    def save_page(self, url: str) -> dict:
        """
        Fetch a web page, extract its main content, and save locally.

        Strategy:
          1. Playwright renders the page (JS executed, lazy images loaded)
          2. Mozilla Readability.js runs in the browser — same as Firefox Reader Mode
          3. trafilatura handles metadata and plain-text output

        Files saved:
          content.html  — reader-mode HTML (div.reader-content)
          content.txt   — plain text body
          content.md    — markdown with header
          metadata.json — title, author, sitename, published_date, source_url
          images/       — downloaded images (local paths replace remote URLs)
        """
        try:
            import trafilatura
            from trafilatura.metadata import extract_metadata as _extract_meta
        except ImportError:
            raise WebpageServiceError(
                'trafilatura is not installed. Run: pip install trafilatura'
            )

        info(f'[WebpageService] Fetching: {url}')

        # --- render with Playwright + run Readability.js in browser ---
        result = self._fetch_with_readability(url)
        if not result:
            raise WebpageServiceError(f'Failed to fetch or extract content from: {url}')

        article_html = result.get('content', '')
        title = (result.get('title') or '').strip()
        author = (result.get('byline') or '').strip()
        excerpt = (result.get('excerpt') or '').strip()

        if not article_html:
            raise WebpageServiceError(f'Readability.js extracted no content from: {url}')

        # --- metadata from trafilatura (better date/sitename extraction) ---
        # Use a static fetch just for metadata (much faster than a second Playwright load)
        static_html = trafilatura.fetch_url(url) or ''
        if static_html:
            meta = _extract_meta(static_html)
            if not title:
                title = (getattr(meta, 'title', None) or '').strip()
            if not author:
                author = (getattr(meta, 'author', None) or '').strip()
            sitename = (getattr(meta, 'sitename', None) or '').strip()
            published_date = (getattr(meta, 'date', None) or '').strip()
            description = (getattr(meta, 'description', None) or excerpt).strip()
        else:
            sitename = ''
            published_date = ''
            description = excerpt

        if not sitename:
            sitename = urllib.parse.urlparse(url).netloc
        if not title:
            title = 'Untitled'

        # --- build save directory ---
        page_id = hashlib.md5(url.encode()).hexdigest()[:12]
        now = datetime.now()
        pub_date = now
        if published_date:
            for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m'):
                try:
                    pub_date = datetime.strptime(published_date[:len(fmt)], fmt)
                    break
                except ValueError:
                    continue

        date_str = pub_date.strftime('%Y-%m-%d')
        clean_title = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', title)[:40].strip('_')
        folder_name = f'{date_str}_{clean_title}_{page_id}'
        post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # --- download images (replace src with local paths) ---
        article_html, image_count = self._download_images(article_html, post_dir, url)

        # --- content.html ---
        reader_html = self._build_reader_html(
            title, author, sitename, published_date, url, article_html
        )
        (post_dir / 'content.html').write_text(reader_html, encoding='utf-8')

        # --- plain text ---
        plain = ''
        if static_html:
            plain = trafilatura.extract(
                static_html, output_format='txt',
                include_links=False, include_images=False, no_fallback=False
            ) or ''
        if not plain:
            from bs4 import BeautifulSoup
            plain = BeautifulSoup(article_html, 'html.parser').get_text(separator='\n')
            plain = re.sub(r'\n{3,}', '\n\n', plain).strip()
        (post_dir / 'content.txt').write_text(plain, encoding='utf-8')

        # --- content.md ---
        md_content = ''
        if static_html:
            md_content = trafilatura.extract(
                static_html, output_format='markdown',
                include_links=True, include_images=False, no_fallback=False
            ) or ''
        if not md_content:
            md_content = plain
        header_lines = [f'# {title}', '']
        if author:
            header_lines.append(f'**Author**: {author}  ')
        header_lines += [f'**Site**: {sitename}  ', f'**Source**: {url}  ']
        if published_date:
            header_lines.append(f'**Published**: {published_date}  ')
        header_lines += ['', '---', '', '']
        (post_dir / 'content.md').write_text('\n'.join(header_lines) + md_content, encoding='utf-8')

        # --- metadata.json ---
        metadata = {
            'page_id': page_id,
            'title': title,
            'author': author,
            'sitename': sitename,
            'published_date': published_date,
            'description': description,
            'source_url': url,
            'image_count': image_count,
            'saved_at': now.isoformat(),
        }
        (post_dir / 'metadata.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        success(f'[WebpageService] Saved "{title}" → {post_dir} ({image_count} images)')
        return {
            'page_id': page_id,
            'title': title,
            'author': author,
            'author_name': author or sitename,
            'author_username': urllib.parse.urlparse(url).netloc,
            'save_path': str(post_dir),
            'image_count': image_count,
            'tweet_text': plain[:500] if plain else description[:500],
        }

    def _fetch_with_readability(self, url: str) -> dict | None:
        """
        Use Playwright to render the page, inject Mozilla Readability.js,
        and run it in the browser context. Returns the parsed article dict
        (title, content, byline, excerpt, etc.) or None on failure.
        """
        try:
            return asyncio.run(self._async_fetch_with_readability(url))
        except Exception as e:
            warning(f'[WebpageService] Readability fetch failed: {e}')
            return None

    async def _async_fetch_with_readability(self, url: str) -> dict:
        from playwright.async_api import async_playwright

        readability_src = _READABILITY_JS.read_text(encoding='utf-8')

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
                      '--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1280, 'height': 900},
                locale='en-US',
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until='networkidle', timeout=30000)
                # Scroll to trigger lazy-loaded images
                await page.evaluate("""
                    async () => {
                        await new Promise(resolve => {
                            let y = 0;
                            const timer = setInterval(() => {
                                window.scrollBy(0, 400);
                                y += 400;
                                if (y >= document.body.scrollHeight) {
                                    clearInterval(timer);
                                    window.scrollTo(0, 0);
                                    resolve();
                                }
                            }, 100);
                        });
                    }
                """)
                await page.wait_for_timeout(1000)

                # Inject and run Readability.js in the browser
                await page.add_script_tag(content=readability_src)
                article = await page.evaluate("""
                    () => {
                        var doc = document.cloneNode(true);
                        var reader = new Readability(doc);
                        return reader.parse();
                    }
                """)
            finally:
                await browser.close()

            return article

    def _download_images(self, html_content: str, post_dir: Path, base_url: str):
        """
        Find all <img> tags, download to images/, replace src with local path.
        Returns (updated_html, count).
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, 'html.parser')
        imgs = soup.find_all('img')
        if not imgs:
            return html_content, 0

        img_dir = post_dir / 'images'
        img_dir.mkdir(exist_ok=True)

        count = 0
        for idx, img in enumerate(imgs, 1):
            src = (img.get('data-src') or img.get('data-lazy-src') or
                   img.get('data-original') or img.get('src') or '').strip()

            if not src or src.startswith('data:'):
                continue

            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                p = urllib.parse.urlparse(base_url)
                src = f'{p.scheme}://{p.netloc}{src}'
            elif not src.startswith('http'):
                continue

            src_clean = src.split('?')[0]
            try:
                req = urllib.request.Request(
                    src, headers={'User-Agent': 'Mozilla/5.0', 'Referer': base_url}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                    if len(data) < 500:
                        continue
                    ct = resp.headers.get('Content-Type', '')
                    ext = ('.png' if 'png' in ct else '.webp' if 'webp' in ct
                           else '.gif' if 'gif' in ct else '.jpg')
                    if not ext and src_clean.lower().endswith(('.png', '.webp', '.gif')):
                        ext = '.' + src_clean.rsplit('.', 1)[-1].lower()
                    fname = f'{idx:02d}{ext}'
                    (img_dir / fname).write_bytes(data)
                    img['src'] = f'images/{fname}'
                    for attr in ('data-src', 'data-lazy-src', 'data-original'):
                        if img.has_attr(attr):
                            del img[attr]
                    count += 1
            except Exception as e:
                warning(f'[WebpageService] Image {idx} failed ({src[:60]}): {e}')

        return str(soup), count

    def _build_reader_html(self, title: str, author: str, sitename: str,
                           published_date: str, url: str, body_html: str) -> str:
        meta_parts = []
        if author:
            meta_parts.append(f'<span>{author}</span>')
        if sitename:
            meta_parts.append(f'<span>{sitename}</span>')
        if published_date:
            meta_parts.append(f'<span>{published_date}</span>')
        meta_parts.append(f'<a href="{url}" target="_blank" rel="noopener">原文链接</a>')
        meta_html = ' · '.join(meta_parts)

        return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title}</title></head>
<body>
<div class="reader-content">
<h1>{title}</h1>
<p style="color:#888;font-size:0.9em;margin-bottom:1.5em">{meta_html}</p>
{body_html}
</div>
</body>
</html>'''

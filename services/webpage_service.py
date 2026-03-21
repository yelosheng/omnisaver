"""
Pocket-style read-later service for arbitrary web pages.
Uses trafilatura for main content extraction.
"""

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from utils.realtime_logger import info, error, warning, success


class WebpageServiceError(Exception):
    pass


class WebpageService:
    """Fetch any web page and save its main content for offline reading."""

    SAVE_DIR = 'saved_web'

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir) / 'saved_tweets')
        self.base_path = Path(base_path) / self.SAVE_DIR
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    @staticmethod
    def is_valid_webpage_url(url: str) -> bool:
        return bool(re.match(r'https?://', url.strip()))

    def save_page(self, url: str) -> dict:
        """
        Fetch a web page, extract its main content via trafilatura, and save locally.

        Files saved:
          content.txt   — plain text body
          content.md    — markdown with header
          content.html  — reader-mode HTML (div.reader-content) for the view route
          metadata.json — title, author, sitename, published_date, source_url
          images/       — downloaded images

        Returns dict with keys: page_id, title, author, author_name, author_username,
                                save_path, image_count, tweet_text
        """
        try:
            import trafilatura
            from trafilatura.metadata import extract_metadata as _extract_meta
        except ImportError:
            raise WebpageServiceError('trafilatura is not installed. Run: pip install trafilatura')

        info(f'[WebpageService] Fetching: {url}')
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            raise WebpageServiceError(f'Failed to fetch URL: {url}')

        # --- metadata ---
        meta = _extract_meta(downloaded)
        title = (getattr(meta, 'title', None) or 'Untitled').strip()
        author = (getattr(meta, 'author', None) or '').strip()
        sitename = (getattr(meta, 'sitename', None) or urllib.parse.urlparse(url).netloc).strip()
        published_date = (getattr(meta, 'date', None) or '').strip()
        description = (getattr(meta, 'description', None) or '').strip()

        # --- extract content ---
        common_opts = dict(include_images=True, include_links=True, include_tables=True, no_fallback=False)
        md_content = trafilatura.extract(downloaded, output_format='markdown', **common_opts) or ''
        html_content = trafilatura.extract(downloaded, output_format='html', **common_opts) or ''

        if not md_content and not html_content:
            raise WebpageServiceError(f'Could not extract readable content from: {url}')

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

        # --- download images ---
        image_count = 0
        if html_content:
            html_content, image_count = self._download_images(html_content, post_dir, url)

        # --- content.html ---
        reader_html = self._build_reader_html(
            title, author, sitename, published_date, url,
            html_content or f'<p>{description}</p>'
        )
        (post_dir / 'content.html').write_text(reader_html, encoding='utf-8')

        # --- content.md ---
        header_lines = [f'# {title}', '']
        if author:
            header_lines.append(f'**Author**: {author}  ')
        header_lines += [
            f'**Site**: {sitename}  ',
            f'**Source**: {url}  ',
        ]
        if published_date:
            header_lines.append(f'**Published**: {published_date}  ')
        header_lines += ['', '---', '', '']
        (post_dir / 'content.md').write_text('\n'.join(header_lines) + md_content, encoding='utf-8')

        # --- content.txt ---
        plain = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', md_content)
        plain = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', plain)
        plain = re.sub(r'[#*`>_~]', '', plain)
        plain = re.sub(r'\n{3,}', '\n\n', plain).strip()
        if not plain:
            plain = description
        (post_dir / 'content.txt').write_text(plain, encoding='utf-8')

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

        success(f'[WebpageService] Saved "{title}" to {post_dir}')
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

    def _download_images(self, html_content: str, post_dir: Path, base_url: str):
        """Download <img> src URLs, replace with local paths. Returns (updated_html, count)."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, 'html.parser')
        imgs = soup.find_all('img', src=True)
        if not imgs:
            return html_content, 0

        img_dir = post_dir / 'images'
        img_dir.mkdir(exist_ok=True)

        count = 0
        for idx, img in enumerate(imgs, 1):
            src = img['src']
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                p = urllib.parse.urlparse(base_url)
                src = f'{p.scheme}://{p.netloc}{src}'
            elif not src.startswith('http'):
                continue  # skip data: URIs and other schemes

            try:
                req = urllib.request.Request(
                    src, headers={'User-Agent': 'Mozilla/5.0', 'Referer': base_url}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                    ct = resp.headers.get('Content-Type', '')
                    ext = ('.png' if 'png' in ct else '.webp' if 'webp' in ct
                           else '.gif' if 'gif' in ct else '.jpg')
                    fname = f'{idx:02d}{ext}'
                    (img_dir / fname).write_bytes(data)
                    img['src'] = f'images/{fname}'
                    count += 1
            except Exception as e:
                warning(f'[WebpageService] Image {idx} download failed: {e}')

        return str(soup), count

    def _build_reader_html(self, title: str, author: str, sitename: str,
                           published_date: str, url: str, body_html: str) -> str:
        """Build content.html with div.reader-content for the view route."""
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
<p class="article-meta" style="color:#888;font-size:0.9em;margin-bottom:1.5em">{meta_html}</p>
{body_html}
</div>
</body>
</html>'''

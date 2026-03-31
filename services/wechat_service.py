import asyncio
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from utils.realtime_logger import info, error, warning, success

# Add wechat-article-for-ai to path
_WECHAT_TOOL_PATH = os.path.expanduser('~/.agent-reach/tools/wechat-article-for-ai')
if _WECHAT_TOOL_PATH not in sys.path:
    sys.path.insert(0, _WECHAT_TOOL_PATH)


class WechatServiceError(Exception):
    pass


class WechatService:
    """WeChat Official Account article archiver."""

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir) / 'saved_tweets')
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_valid_wechat_url(url: str) -> bool:
        return bool(re.match(r'https?://mp\.weixin\.qq\.com/', url))

    @staticmethod
    def _extract_carousel_image_urls(html: str) -> list:
        """Extract image URLs from XHS-style carousel (window.picture_page_info_list)."""
        m = re.search(r'window\.picture_page_info_list\s*=\s*\[(.*?)\]\.slice\(', html, re.DOTALL)
        if not m:
            return []
        block = m.group(1)
        urls = []
        # Split into individual items; take the FIRST cdn_url in each (top-level image, not nested)
        for item in re.split(r'\},\s*\{', block):
            m2 = re.search(r"cdn_url\s*:\s*['\"]([^'\"]+)['\"]", item)
            if m2 and m2.group(1):
                urls.append(m2.group(1))
        return urls

    @staticmethod
    def extract_article_id(url: str) -> str:
        """Return a stable short ID for the article URL."""
        parsed = urllib.parse.urlparse(url)
        # Short URL: /s/XXXXXXX
        m = re.match(r'/s/([A-Za-z0-9_-]+)', parsed.path)
        if m:
            return m.group(1)
        # Long URL: ?__biz=...&sn=... — use sn
        qs = urllib.parse.parse_qs(parsed.query)
        sn = qs.get('sn', [''])[0]
        if sn:
            return sn[:16]
        # Fallback: hash of URL
        return hashlib.md5(url.encode()).hexdigest()[:12]

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def save_article(self, url: str) -> dict:
        """
        Fetch a WeChat 公众号 article and save it locally.

        Files follow the same layout as Twitter/XHS posts:
          content.txt     — plain text article body
          content.md      — markdown with frontmatter
          metadata.json   — title, author, publish_time, url
          images/         — locally downloaded images (01.jpg, 02.jpg, …)

        Returns:
            dict with keys: article_id, title, author, save_path,
                            image_count, tweet_text
        """
        if not self.is_valid_wechat_url(url):
            raise WechatServiceError(f'Invalid WeChat article URL: {url}')

        try:
            from wechat_to_md.scraper import fetch_page_html
            from wechat_to_md.parser import extract_metadata, process_content
            from wechat_to_md.converter import build_markdown, convert_html_to_markdown
            from bs4 import BeautifulSoup
        except ImportError as e:
            raise WechatServiceError(
                f'wechat_to_md not available: {e}. '
                f'Ensure {_WECHAT_TOOL_PATH} exists and dependencies are installed.'
            )

        info(f'Fetching WeChat article: {url}')

        def _run(coro):
            """Run a coroutine safely whether or not an event loop is already running."""
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, coro).result()

        # Fetch and parse
        html = _run(fetch_page_html(url, headless=True))
        soup = BeautifulSoup(html, 'html.parser')
        meta = extract_metadata(soup, html, url=url)

        # Fallback for newer XHS-style article format that uses different selectors
        if not meta.title:
            title_el = soup.select_one('.rich_media_title') or soup.select_one('h1')
            if title_el:
                meta.title = title_el.get_text(strip=True)
        if not meta.author:
            author_el = soup.select_one('.wx_follow_nickname')
            if author_el:
                meta.author = author_el.get_text(strip=True)

        if not meta.title:
            raise WechatServiceError('Could not extract article title — page may be a CAPTCHA or invalid URL')

        info(f'Title: {meta.title}')
        parsed = process_content(soup)

        # Build directory
        article_id = self.extract_article_id(url)
        now = datetime.now()
        # Parse publish_time if available for accurate dating
        pub_date = now
        if meta.publish_time:
            try:
                pub_date = datetime.strptime(meta.publish_time, '%Y-%m-%d')
            except ValueError:
                pass

        date_str = pub_date.strftime('%Y-%m-%d')
        folder_name = f'{date_str}_{article_id}'
        if self.create_date_folders:
            post_dir = self.base_path / pub_date.strftime('%Y') / pub_date.strftime('%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # Inject video placeholders into content HTML before markdown conversion
        # so that video positions are preserved inline in the resulting markdown.
        # Replace the entire player container (not just the <video> tag) to strip
        # all surrounding UI elements (controls, share overlay, related-article section).
        content_soup = BeautifulSoup(parsed.content_html, 'html.parser')
        video_tags = content_soup.find_all('video', src=True)
        video_info = []  # [(placeholder, src, poster), ...]
        _PLAYER_CLASSES = {'feed-wrapper', 'mp-video-player', 'page_video_wrapper', 'js_mpvedio'}
        for v_idx, vtag in enumerate(video_tags, 1):
            placeholder = f'WECHATVIDEO{v_idx}HERE'
            video_info.append((placeholder, vtag.get('src', ''), vtag.get('poster', '')))
            # Walk up to find the outermost player container (keep going — don't
            # break on first match, so we reach mp-video-player not just page_video_wrapper)
            container = vtag
            for ancestor in vtag.parents:
                if ancestor.name in (None, '[document]', 'html', 'body'):
                    break
                classes = set(ancestor.get('class') or [])
                if classes & _PLAYER_CLASSES:
                    container = ancestor  # update but keep walking up
            container.replace_with(content_soup.new_tag('p', string=placeholder))
        patched_html = str(content_soup)

        # Convert content to markdown (with video placeholders in place)
        md_body = convert_html_to_markdown(patched_html, parsed.code_blocks)

        # Extract image URLs directly from the converted markdown (authoritative source)
        # Pattern: ![alt](URL) — URL may contain #imgIndex=N fragments
        md_image_urls = re.findall(r'!\[[^\]]*\]\((https://[^)]+)\)', md_body)

        # Download images → images/01.jpg, 02.jpg, … and replace URLs in markdown
        image_count = 0
        if md_image_urls:
            img_dir = post_dir / 'images'
            img_dir.mkdir(exist_ok=True)
            seen = {}  # md_url → local_rel (avoid re-downloading duplicates)
            idx = 1
            for md_url in md_image_urls:
                if md_url in seen:
                    md_body = md_body.replace(md_url, seen[md_url])
                    continue
                clean_url = md_url.split('#')[0]
                last_err = None
                for attempt in range(3):
                    try:
                        if attempt:
                            import time as _t; _t.sleep(1.5 * attempt)
                        req = urllib.request.Request(
                            clean_url,
                            headers={
                                'User-Agent': 'Mozilla/5.0',
                                'Referer': 'https://mp.weixin.qq.com/',
                            }
                        )
                        with urllib.request.urlopen(req, timeout=20) as resp:
                            data = resp.read()
                            ct = resp.headers.get('Content-Type', '')
                            if 'png' in ct:
                                ext = '.png'
                            elif 'webp' in ct:
                                ext = '.webp'
                            elif 'gif' in ct:
                                ext = '.gif'
                            else:
                                ext = '.jpg'
                            fname = f'{idx:02d}{ext}'
                            (img_dir / fname).write_bytes(data)
                            local_rel = f'images/{fname}'
                            md_body = md_body.replace(md_url, local_rel)
                            seen[md_url] = local_rel
                            image_count += 1
                            idx += 1
                            last_err = None
                            break
                    except Exception as e:
                        last_err = e
                if last_err:
                    warning(f'Image {idx} download failed after 3 attempts: {last_err}')
                    seen[md_url] = md_url  # keep remote URL on failure

        # For XHS-style carousel articles: images are in JS data, not in the HTML content.
        # Extract from window.picture_page_info_list and append to markdown.
        carousel_urls = self._extract_carousel_image_urls(html)
        if carousel_urls:
            img_dir = post_dir / 'images'
            img_dir.mkdir(exist_ok=True)
            carousel_lines = []
            idx = image_count + 1  # continue numbering after any inline images
            for c_url in carousel_urls:
                last_err = None
                for attempt in range(3):
                    try:
                        if attempt:
                            import time as _t; _t.sleep(1.5 * attempt)
                        req = urllib.request.Request(
                            c_url,
                            headers={
                                'User-Agent': 'Mozilla/5.0',
                                'Referer': 'https://mp.weixin.qq.com/',
                            }
                        )
                        with urllib.request.urlopen(req, timeout=20) as resp:
                            data = resp.read()
                            ct = resp.headers.get('Content-Type', '')
                            ext = '.png' if 'png' in ct else '.webp' if 'webp' in ct else '.gif' if 'gif' in ct else '.jpg'
                            fname = f'{idx:02d}{ext}'
                            (img_dir / fname).write_bytes(data)
                            carousel_lines.append(f'![图{idx}](images/{fname})')
                            image_count += 1
                            idx += 1
                            last_err = None
                            break
                    except Exception as e:
                        last_err = e
                if last_err:
                    warning(f'Carousel image {idx} download failed: {last_err}')
                    carousel_lines.append(f'![图{idx}]({c_url})')
                    idx += 1
            if carousel_lines:
                md_body = md_body.rstrip() + '\n\n' + '\n\n'.join(carousel_lines) + '\n'

        # Download videos and replace inline placeholders in markdown
        video_count = 0
        if video_info:
            vid_dir = post_dir / 'videos'
            vid_dir.mkdir(exist_ok=True)
            for v_idx, (placeholder, v_src_full, v_poster) in enumerate(video_info, 1):
                if not v_src_full:
                    md_body = md_body.replace(placeholder, '')
                    continue
                v_fname = f'video{v_idx:02d}.mp4'
                try:
                    req = urllib.request.Request(
                        v_src_full,
                        headers={
                            'User-Agent': 'Mozilla/5.0',
                            'Referer': 'https://mp.weixin.qq.com/',
                        }
                    )
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        (vid_dir / v_fname).write_bytes(resp.read())
                    local_vid = f'videos/{v_fname}'
                    md_body = md_body.replace(placeholder, f'[视频 {v_idx}]({local_vid})')
                    video_count += 1
                    info(f'Video {v_idx} saved: {v_fname}')
                    # Save poster/thumbnail
                    if v_poster:
                        try:
                            preq = urllib.request.Request(
                                v_poster, headers={'User-Agent': 'Mozilla/5.0'}
                            )
                            with urllib.request.urlopen(preq, timeout=15) as presp:
                                (vid_dir / f'poster{v_idx:02d}.jpg').write_bytes(presp.read())
                        except Exception:
                            pass
                except Exception as e:
                    warning(f'Video {v_idx} download failed: {e}')
                    md_body = md_body.replace(placeholder, '')  # remove placeholder on failure

        # content.txt — strip all markdown image/link syntax for plain text display
        plain = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', md_body)   # remove ![alt](url) entirely
        plain = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', plain)  # [text](url) → text
        plain = re.sub(r'[#*`>_~]', '', plain)
        plain = re.sub(r'\n{3,}', '\n\n', plain).strip()
        (post_dir / 'content.txt').write_text(plain, encoding='utf-8')

        # content.md — full markdown with header
        full_md = '\n'.join([
            f'# {meta.title}',
            '',
            f'**作者**: {meta.author}  ',
            f'**发布时间**: {meta.publish_time}  ',
            '',
            '---',
            '',
            md_body,
        ])
        (post_dir / 'content.md').write_text(full_md, encoding='utf-8')

        # metadata.json
        metadata = {
            'article_id': article_id,
            'title': meta.title,
            'author': meta.author,
            'publish_time': meta.publish_time,
            'source_url': url,
            'image_count': image_count,
            'video_count': video_count,
            'saved_at': now.isoformat(),
        }
        (post_dir / 'metadata.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        success(f'WeChat article saved to {post_dir}')
        return {
            'article_id': article_id,
            'title': meta.title,
            'author': meta.author,
            'save_path': str(post_dir),
            'image_count': image_count,
            'tweet_text': plain[:500],
            'author_username': '',
            'author_name': meta.author,
        }

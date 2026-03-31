import asyncio
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
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

    _COOKIES_PATH = os.path.expanduser('~/.agent-reach/wechat/cookies.json')
    _GENERIC_TITLES = {'Weixin Official Accounts Platform', '微信公众平台', ''}
    _ALBUM_NOISE_LINES = {
        'Close', '更多', 'Name cleared', '微信扫一扫赞赏作者', 'Like the Author',
        'Other Amount', '赞赏后展示我的头像', '作品', '暂无作品', '¥', '最低赞赏 ¥0',
        'OK', 'Back', '赞赏金额', 'Like', 'Share', 'Popular', 'Comment', 'Loading...'
    }
    _CAPTCHA_INDICATORS = (
        'js_verify',
        'verify_container',
        '环境异常',
        '请完成安全验证',
        '操作频繁',
    )

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
    def _extract_swiper_image_urls(soup) -> list[str]:
        """Extract image URLs from album/swiper-style pages."""
        urls = []
        seen = set()
        for el in soup.select('.swiper_item[data-src], #img_list .swiper_item[data-src]'):
            url = (el.get('data-src') or '').strip()
            if not url:
                continue
            canonical = re.sub(r'([?&])wx_fmt=[^&]+', '', url)
            canonical = re.sub(r'([?&])tp=[^&]+', '', canonical)
            canonical = re.sub(r'([?&])wxfrom=[^&]+', '', canonical)
            canonical = canonical.rstrip('?&')
            if canonical not in seen:
                seen.add(canonical)
                urls.append(url)
        return urls

    @classmethod
    def _extract_album_page_text(cls, soup) -> str:
        """Extract clean text for image-album pages from the primary content container."""
        content_el = (
            soup.select_one('#js_content_top_container')
            or soup.select_one('#js_article_content')
            or soup.select_one('.rich_media_area_primary_inner')
            or soup.select_one('#js_content')
            or soup.select_one('#js_image_content')
        )
        if not content_el:
            return ''
        raw_text = cls._normalize_rich_text(content_el.get_text('\n\n', strip=True))
        cleaned_lines = []
        for line in raw_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            if line in cls._ALBUM_NOISE_LINES:
                continue
            if re.fullmatch(r'[0-9]+', line):
                continue
            if re.fullmatch(r'[.,;:，。；：]+', line):
                continue
            cleaned_lines.append(line)
        text = cls._normalize_rich_text('\n'.join(cleaned_lines))
        return cls._escape_markdown_headers(text) if text else ''

    @staticmethod
    def _normalize_rich_text(text: str) -> str:
        text = text.replace('\xa0', ' ').replace('\u200b', '')
        text = re.sub(r'\r\n?', '\n', text)
        text = re.sub(r'[ \t]+\n', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    @classmethod
    def _escape_markdown_headers(cls, text: str) -> str:
        """Prevent plain text hashtag lines from becoming Markdown headers."""
        lines = []
        for line in text.split('\n'):
            stripped = line.lstrip()
            if stripped.startswith('#'):
                indent = line[:len(line) - len(stripped)]
                lines.append(f'{indent}\\{stripped}')
            else:
                lines.append(line)
        return '\n'.join(lines)

    @classmethod
    def _extract_share_description_markdown(cls, soup, html: str) -> str:
        """Extract text from image/share style pages that do not use normal article body."""
        for selector in ('#js_image_desc', '#js_common_share_desc'):
            el = soup.select_one(selector)
            if el:
                text = cls._normalize_rich_text(el.get_text('\n\n', strip=True))
                if text:
                    return cls._escape_markdown_headers(text)

        for element_id in ('js_image_desc', 'js_common_share_desc'):
            m = re.search(
                rf'document\.getElementById\([\'"]{element_id}[\'"]\)\.innerHTML\s*=\s*"((?:\\.|[^"\\])*)"',
                html,
                re.DOTALL,
            )
            if not m:
                continue
            try:
                text = json.loads(f'"{m.group(1)}"')
            except json.JSONDecodeError:
                continue
            text = cls._normalize_rich_text(text)
            if text:
                return cls._escape_markdown_headers(text)

        return ''

    @classmethod
    def _is_captcha_page(cls, html: str) -> bool:
        return any(indicator in html for indicator in cls._CAPTCHA_INDICATORS)

    @classmethod
    def _score_rendered_html(cls, html: str) -> int:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        score = 0
        title_el = soup.select_one('#activity-name') or soup.select_one('.rich_media_title') or soup.select_one('h1')
        if title_el and title_el.get_text(strip=True):
            score += 80

        for selector in ('#js_image_desc', '#js_common_share_desc', '#js_content', '.rich_media_content'):
            el = soup.select_one(selector)
            if not el:
                continue
            text = cls._normalize_rich_text(el.get_text('\n\n', strip=True))
            score = max(score, len(text) + 80)

        if 'window.picture_page_info_list' in html:
            score += 40

        return score

    def _fetch_page_html(self, url: str, headless: bool = True) -> str:
        from camoufox.async_api import AsyncCamoufox

        async def _fetch() -> str:
            async with AsyncCamoufox(headless=headless) as browser:
                page = await browser.new_page()
                if os.path.exists(self._COOKIES_PATH):
                    try:
                        cookies_list = json.loads(Path(self._COOKIES_PATH).read_text(encoding='utf-8'))
                        valid_cookies = []
                        for c in cookies_list if isinstance(cookies_list, list) else []:
                            if not isinstance(c, dict) or not c.get('name'):
                                continue
                            valid_cookies.append({
                                'name': c['name'],
                                'value': c.get('value', ''),
                                'domain': c.get('domain', '.mp.weixin.qq.com'),
                                'path': c.get('path', '/'),
                            })
                        if valid_cookies:
                            await page.context.add_cookies(valid_cookies)
                            info(f'Loaded {len(valid_cookies)} WeChat cookies from {self._COOKIES_PATH}')
                    except Exception as e:
                        warning(f'Failed to load WeChat cookies: {e}')
                await page.goto(url, wait_until='domcontentloaded')

                async def _safe_page_content():
                    last_error = None
                    for _ in range(8):
                        try:
                            return await page.content()
                        except Exception as e:
                            last_error = e
                            await asyncio.sleep(0.5)
                    raise last_error

                async def _read_runtime_share():
                    return await page.evaluate(
                        """
                        () => {
                            const normalize = (text) => (text || '')
                                .replace(/\\u00a0/g, ' ')
                                .replace(/\\u200b/g, '')
                                .replace(/[ \\t]+\\n/g, '\\n')
                                .replace(/\\n{3,}/g, '\\n\\n')
                                .trim();

                            const shareEl = document.querySelector('#js_image_desc') || document.querySelector('#js_common_share_desc');
                            if (!shareEl) return null;
                            return {
                                id: shareEl.id || 'js_image_desc',
                                className: shareEl.className || '',
                                html: shareEl.innerHTML || '',
                                text: normalize(shareEl.innerText || ''),
                            };
                        }
                        """
                    )

                async def _read_runtime_state():
                    return await page.evaluate(
                        """
                        () => {
                            const norm = (text) => String(text || '').trim();
                            const shareEl = document.querySelector('#js_image_desc') || document.querySelector('#js_common_share_desc');
                            const contentEl = document.querySelector('#js_content') || document.querySelector('#js_image_content');
                            return {
                                title: norm(document.title),
                                shareTextLen: shareEl ? norm(shareEl.innerText).length : 0,
                                contentTextLen: contentEl ? norm(contentEl.innerText).length : 0,
                                swiperCount: document.querySelectorAll('.swiper_item[data-src]').length,
                            };
                        }
                        """
                    )

                runtime_payload = None
                for _ in range(40):
                    await asyncio.sleep(0.5)
                    html = await _safe_page_content()
                    if self._is_captcha_page(html):
                        raise WechatServiceError(
                            'WeChat verification/CAPTCHA detected. Please retry after solving verification in a browser session.'
                        )
                    runtime_payload = await _read_runtime_share()
                    runtime_state = await _read_runtime_state()
                    title_ready = runtime_state.get('title', '') not in self._GENERIC_TITLES
                    share_ready = runtime_payload and len((runtime_payload.get('text') or '').strip()) >= 12
                    content_ready = runtime_state.get('contentTextLen', 0) >= 20
                    swiper_ready = runtime_state.get('swiperCount', 0) > 0
                    if title_ready and (share_ready or content_ready or swiper_ready):
                        break

                html = await _safe_page_content()
                runtime_payload = runtime_payload or await _read_runtime_share()
                runtime_payload = {'share': runtime_payload} if runtime_payload else {'share': None}
                final_html = html
                share_payload = runtime_payload.get('share')
                if share_payload and share_payload.get('html') and len((share_payload.get('text') or '').strip()) >= 120:
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(final_html, 'html.parser')
                    existing = soup.select_one('#js_image_desc') or soup.select_one('#js_common_share_desc')
                    if existing:
                        existing.decompose()

                    injected = soup.new_tag('p', id=share_payload.get('id') or 'js_image_desc')
                    class_name = share_payload.get('className', '')
                    if class_name:
                        injected['class'] = class_name.split()
                    fragment = BeautifulSoup(share_payload['html'], 'html.parser')
                    for child in list(fragment.contents):
                        injected.append(child)
                    if soup.body:
                        soup.body.append(injected)
                    else:
                        soup.append(injected)
                    final_html = str(soup)

                return final_html

        def _run(coro):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, coro).result()

        return _run(_fetch())

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
            from wechat_to_md.parser import extract_metadata, process_content
            from wechat_to_md.converter import build_markdown, convert_html_to_markdown
            from bs4 import BeautifulSoup
        except ImportError as e:
            raise WechatServiceError(
                f'wechat_to_md not available: {e}. '
                f'Ensure {_WECHAT_TOOL_PATH} exists and dependencies are installed.'
            )

        info(f'Fetching WeChat article: {url}')

        # Fetch and parse
        html = self._fetch_page_html(url, headless=True)
        soup = BeautifulSoup(html, 'html.parser')
        meta = extract_metadata(soup, html, url=url)

        # Fallback for newer XHS-style article format that uses different selectors
        if not meta.title:
            title_el = (
                soup.select_one('.rich_media_title')
                or soup.select_one('#activity-name')
                or soup.select_one('#js_image_desc')
                or soup.select_one('h1')
                or soup.select_one('title')
            )
            if title_el:
                title_text = title_el.get_text(strip=True)
                if title_text not in self._GENERIC_TITLES:
                    meta.title = title_text
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
        image_hashes = {}
        img_dir = post_dir / 'images'
        if img_dir.exists():
            shutil.rmtree(img_dir)

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

        swiper_urls = self._extract_swiper_image_urls(soup)
        album_text_md = self._extract_album_page_text(soup) if swiper_urls else ''
        runtime_text_md = self._extract_share_description_markdown(soup, html)
        if album_text_md:
            md_body = album_text_md
        elif runtime_text_md:
            existing_text = self._normalize_rich_text(re.sub(r'!\[[^\]]*\]\([^)]*\)', '', md_body))
            runtime_compact = re.sub(r'\s+', '', runtime_text_md)
            existing_compact = re.sub(r'\s+', '', existing_text)
            if runtime_compact and len(runtime_compact) > len(existing_compact):
                info('Using runtime-rendered WeChat text as the primary article body')
                md_body = runtime_text_md
            elif runtime_compact and runtime_compact not in existing_compact:
                md_body = (md_body.rstrip() + '\n\n' + runtime_text_md + '\n').strip()

        # Extract image URLs directly from the converted markdown (authoritative source)
        # Pattern: ![alt](URL) — URL may contain #imgIndex=N fragments
        md_image_urls = re.findall(r'!\[[^\]]*\]\((https://[^)]+)\)', md_body)

        # Download images → images/01.jpg, 02.jpg, … and replace URLs in markdown
        image_count = 0
        if md_image_urls:
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
                            data_hash = hashlib.sha256(data).hexdigest()
                            if data_hash in image_hashes:
                                local_rel = image_hashes[data_hash]
                                md_body = md_body.replace(md_url, local_rel)
                                seen[md_url] = local_rel
                                last_err = None
                                break
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
                            image_hashes[data_hash] = local_rel
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
                            data_hash = hashlib.sha256(data).hexdigest()
                            if data_hash in image_hashes:
                                last_err = None
                                break
                            ct = resp.headers.get('Content-Type', '')
                            ext = '.png' if 'png' in ct else '.webp' if 'webp' in ct else '.gif' if 'gif' in ct else '.jpg'
                            fname = f'{idx:02d}{ext}'
                            (img_dir / fname).write_bytes(data)
                            local_rel = f'images/{fname}'
                            carousel_lines.append(f'![图{idx}]({local_rel})')
                            image_hashes[data_hash] = local_rel
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

        if swiper_urls:
            img_dir.mkdir(exist_ok=True)
            swiper_lines = []
            idx = image_count + 1
            for s_url in swiper_urls:
                last_err = None
                clean_url = s_url.split('#')[0]
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
                            data_hash = hashlib.sha256(data).hexdigest()
                            if data_hash in image_hashes:
                                last_err = None
                                break
                            ct = resp.headers.get('Content-Type', '')
                            ext = '.png' if 'png' in ct else '.webp' if 'webp' in ct else '.gif' if 'gif' in ct else '.jpg'
                            fname = f'{idx:02d}{ext}'
                            (img_dir / fname).write_bytes(data)
                            local_rel = f'images/{fname}'
                            swiper_lines.append(f'![图{idx}]({local_rel})')
                            image_hashes[data_hash] = local_rel
                            image_count += 1
                            idx += 1
                            last_err = None
                            break
                    except Exception as e:
                        last_err = e
                if last_err:
                    warning(f'Swiper image {idx} download failed: {last_err}')
                    swiper_lines.append(f'![图{idx}]({clean_url})')
                    idx += 1
            if swiper_lines:
                md_body = md_body.rstrip() + '\n\n' + '\n\n'.join(swiper_lines) + '\n'

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

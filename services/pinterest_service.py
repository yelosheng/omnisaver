import asyncio
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from utils.realtime_logger import info, success, warning


class PinterestServiceError(Exception):
    pass


class PinterestService:
    """Pinterest pin downloader service using Playwright."""

    _PIN_URL_RE = re.compile(
        r'https?://(?:[\w-]+\.)?pinterest\.[a-z.]+/pin/(\d+)(?:[/?][^\s]*)?',
        re.IGNORECASE,
    )
    _SHORT_URL_RE = re.compile(
        r'https?://pin\.it/([A-Za-z0-9]+)(?:[/?][^\s]*)?',
        re.IGNORECASE,
    )
    _URL_RE = re.compile(
        r'https?://(?:pin\.it/[A-Za-z0-9]+|(?:[\w-]+\.)?pinterest\.[a-z.]+/pin/\d+(?:[/?][^\s]*)?)',
        re.IGNORECASE,
    )

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir) / 'saved_tweets')
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    @classmethod
    def is_valid_pinterest_url(cls, url: str) -> bool:
        return bool(url and cls._URL_RE.search(url.strip()))

    @classmethod
    def extract_url_from_share_text(cls, text: str) -> str:
        m = cls._URL_RE.search(text or '')
        return m.group(0).rstrip(').,!?') if m else ''

    def _resolve_short_url(self, url: str) -> str:
        if not self._SHORT_URL_RE.search(url or ''):
            return url
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/123.0.0.0 Safari/537.36'
                    )
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                resolved = response.geturl()
            info(f'[Pinterest] Resolved short URL: {url} -> {resolved}')
            return resolved
        except Exception as e:
            warning(f'[Pinterest] Failed to resolve short URL {url}: {e}')
            return url

    @classmethod
    def _normalize_pin_url(cls, url: str) -> str:
        m = cls._PIN_URL_RE.search(url or '')
        if not m:
            return url
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc or 'www.pinterest.com'
        if not netloc.startswith('www.'):
            netloc = f'www.{netloc}'
        return f'{parsed.scheme or "https"}://{netloc}/pin/{m.group(1)}/'

    async def _collect_page_data(self, page) -> dict:
        return await page.evaluate(
            """() => {
                const meta = (selector) => document.querySelector(selector)?.content?.trim() || '';
                const text = (selector) => document.querySelector(selector)?.innerText?.trim() || '';
                const unique = (arr) => [...new Set(arr.filter(Boolean))];

                let jsonLd = {};
                for (const node of document.querySelectorAll('script[type="application/ld+json"]')) {
                    try {
                        const parsed = JSON.parse(node.textContent);
                        const items = Array.isArray(parsed) ? parsed : [parsed];
                        for (const item of items) {
                            if (!item || typeof item !== 'object') continue;
                            if (item['@type'] === 'ImageObject' || item['@type'] === 'VideoObject' || item['@type'] === 'SocialMediaPosting') {
                                jsonLd = item;
                                break;
                            }
                        }
                    } catch (e) {}
                    if (Object.keys(jsonLd).length) break;
                }

                const title =
                    meta('meta[property="og:title"]') ||
                    meta('meta[name="twitter:title"]') ||
                    jsonLd.name ||
                    text('h1');

                const description =
                    meta('meta[property="og:description"]') ||
                    meta('meta[name="description"]') ||
                    jsonLd.description ||
                    text('[data-test-id="pin-description"]');

                const author =
                    (jsonLd.author && (jsonLd.author.name || jsonLd.author.alternateName)) ||
                    text('a[href*="/_created/"], a[data-test-id="creator-link"]') ||
                    '';

                const avatar =
                    document.querySelector('img[srcset][alt*="profile" i]')?.currentSrc ||
                    document.querySelector('img[src*="profile"], img[alt*="profile" i]')?.src ||
                    '';

                const video =
                    document.querySelector('video')?.currentSrc ||
                    document.querySelector('video source')?.src ||
                    '';

                const poster =
                    document.querySelector('video')?.poster ||
                    meta('meta[property="og:image"]') ||
                    (Array.isArray(jsonLd.thumbnailUrl) ? jsonLd.thumbnailUrl[0] : jsonLd.thumbnailUrl) ||
                    '';

                const imageCandidates = unique([
                    meta('meta[property="og:image"]'),
                    Array.isArray(jsonLd.image) ? jsonLd.image[0] : jsonLd.image,
                    ...Array.from(document.images)
                        .map((img) => img.currentSrc || img.src)
                        .filter((src) => /pinimg\\.com|media-cache/.test(src || ''))
                ]);

                return {
                    final_url: location.href,
                    title,
                    description,
                    author,
                    avatar,
                    video,
                    poster,
                    images: imageCandidates
                };
            }"""
        )

    async def _fetch_pin_data_async(self, url: str) -> dict:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage'],
            )
            context = await browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) '
                    'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 '
                    'Mobile/15E148 Safari/604.1'
                ),
                viewport={'width': 430, 'height': 932},
            )
            page = await context.new_page()
            await page.route(
                '**/*',
                lambda route: route.continue_()
                if route.request.resource_type in ['document', 'script', 'xhr', 'fetch', 'media']
                else route.abort()
            )

            media_urls = []

            async def handle_response(response):
                try:
                    content_type = (response.headers.get('content-type') or '').lower()
                    if 'video/' in content_type and response.url not in media_urls:
                        media_urls.append(response.url)
                except Exception:
                    pass

            page.on('response', handle_response)

            try:
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=20000)
                except Exception as e:
                    warning(f'[Pinterest] Navigation timeout/error, continuing with partial DOM: {e}')
                await page.wait_for_timeout(1200)
                data = await self._collect_page_data(page)
                if not any([data.get('title'), data.get('description'), data.get('video'), data.get('images')]):
                    try:
                        await page.wait_for_load_state('load', timeout=5000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(1000)
                    data = await self._collect_page_data(page)
            finally:
                await browser.close()

        data['captured_videos'] = media_urls
        return data

    def _download_file(self, url: str, dest_path: Path, referer: str):
        if not url:
            return
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/123.0.0.0 Safari/537.36'
                ),
                'Referer': referer,
            },
        )
        with urllib.request.urlopen(req, timeout=60) as response, open(dest_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)

    def save_pin(self, url: str) -> dict:
        if not self.is_valid_pinterest_url(url):
            raise PinterestServiceError(f'Invalid Pinterest URL: {url}')

        resolved_url = self._normalize_pin_url(self._resolve_short_url(url))
        info(f'[Pinterest] Fetching pin: {resolved_url}')

        try:
            meta = asyncio.run(self._fetch_pin_data_async(resolved_url))
        except Exception as e:
            raise PinterestServiceError(f'Playwright extraction failed: {e}')

        final_url = meta.get('final_url') or resolved_url
        normalized_url = self._normalize_pin_url(final_url)
        pin_match = self._PIN_URL_RE.search(normalized_url)
        if not pin_match:
            raise PinterestServiceError(f'Could not resolve a canonical pin URL from: {final_url}')
        pin_id = pin_match.group(1)

        title = (meta.get('title') or '').strip()
        description = (meta.get('description') or '').strip()
        author_name = (meta.get('author') or '').strip() or 'Pinterest User'
        avatar_url = (meta.get('avatar') or '').strip()
        poster_url = (meta.get('poster') or '').strip()

        video_url = (meta.get('video') or '').strip()
        if not video_url:
            for candidate in meta.get('captured_videos', []):
                if '.mp4' in candidate or 'video' in candidate:
                    video_url = candidate
                    break

        image_urls = []
        for candidate in meta.get('images', []):
            if candidate and candidate not in image_urls and 'profile' not in candidate:
                image_urls.append(candidate)
        if poster_url and poster_url not in image_urls:
            image_urls.insert(0, poster_url)

        summary = description or title or f'Pinterest pin {pin_id}'
        safe_title = re.sub(r'[^\w\u4e00-\u9fff\- ]', '', title or description or 'pinterest_pin')[:40].strip() or 'pinterest_pin'
        save_time = datetime.now()
        folder_name = f'{save_time.strftime("%Y-%m-%d")}_{safe_title}_{pin_id}'
        if self.create_date_folders:
            post_dir = self.base_path / save_time.strftime('%Y') / save_time.strftime('%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        media_count = 0
        md_lines = [f'# {re.sub(r"(?m)^#", r"\\#", title or "Pinterest Pin")}', '']
        md_lines.append(f'**作者**: {author_name}  ')
        md_lines.append(f'**来源**: {normalized_url}  ')
        md_lines.append('')

        if video_url:
            videos_dir = post_dir / 'videos'
            videos_dir.mkdir(exist_ok=True)
            try:
                self._download_file(video_url, videos_dir / 'video.mp4', normalized_url)
                md_lines.extend(['[视频](videos/video.mp4)', ''])
                media_count += 1
            except Exception as e:
                warning(f'[Pinterest] Video download failed: {e}')

            if poster_url:
                thumbs_dir = post_dir / 'thumbnails'
                thumbs_dir.mkdir(exist_ok=True)
                try:
                    self._download_file(poster_url, thumbs_dir / 'cover.jpg', normalized_url)
                except Exception as e:
                    warning(f'[Pinterest] Thumbnail download failed: {e}')
        else:
            images_dir = post_dir / 'images'
            images_dir.mkdir(exist_ok=True)
            for idx, image_url in enumerate(image_urls, start=1):
                ext = '.jpg'
                parsed_path = urllib.parse.urlparse(image_url).path.lower()
                if parsed_path.endswith('.png'):
                    ext = '.png'
                elif parsed_path.endswith('.webp'):
                    ext = '.webp'
                image_name = f'{idx}{ext}'
                try:
                    self._download_file(image_url, images_dir / image_name, normalized_url)
                    md_lines.extend([f'![Pinterest image {idx}](images/{image_name})', ''])
                    media_count += 1
                except Exception as e:
                    warning(f'[Pinterest] Image download failed: {image_url} ({e})')

        if avatar_url:
            try:
                self._download_file(avatar_url, post_dir / 'avatar.jpg', normalized_url)
            except Exception as e:
                warning(f'[Pinterest] Avatar download failed: {e}')

        escaped_summary = re.sub(r'(?m)^#', r'\#', summary)
        md_lines.extend(['---', '', escaped_summary])

        (post_dir / 'content.md').write_text('\n'.join(md_lines).strip() + '\n', encoding='utf-8')
        (post_dir / 'content.txt').write_text(summary, encoding='utf-8')
        (post_dir / 'metadata.json').write_text(
            json.dumps(
                {
                    'id': pin_id,
                    'title': title or summary[:100],
                    'description': description,
                    'author': author_name,
                    'url': normalized_url,
                    'platform': 'pinterest',
                    'saved_at': save_time.isoformat(),
                    'video_url': video_url,
                    'poster_url': poster_url,
                    'image_count': media_count if not video_url else 0,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding='utf-8',
        )

        success(f'[Pinterest] Pin saved to {post_dir}')
        return {
            'pin_id': pin_id,
            'title': title or summary[:100],
            'save_path': str(post_dir),
            'author_username': author_name,
            'author_name': author_name,
            'tweet_text': summary[:500],
            'media_count': media_count,
        }

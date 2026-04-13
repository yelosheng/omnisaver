import asyncio
import html
import json
import os
import re
import shutil
import hashlib
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

    @staticmethod
    def _extract_author_from_description(description: str) -> str:
        text = (description or '').strip()
        if not text:
            return ''
        patterns = [
            r'\bdiscovered by\s+([^.,|]+)',
            r'\bpin is ontdekt door\s+([^.,|]+)',
            r'\bdeze pin is ontdekt door\s+([^.,|]+)',
            r'\bdescubierto por\s+([^.,|]+)',
            r'\bdécouverte par\s+([^.,|]+)',
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return html.unescape(m.group(1)).strip()
        return ''

    @staticmethod
    def _pinimg_canonical_key(url: str) -> str:
        if not url:
            return ''
        parsed = urllib.parse.urlparse(url)
        parts = [p for p in parsed.path.split('/') if p]
        if 'pinimg.com' in (parsed.netloc or '') and len(parts) >= 4:
            size_tokens = {'originals', '236x', '474x', '564x', '736x', '1200x', '1200x630', '170x', '75x75_RS'}
            if parts[0] in size_tokens:
                parts = parts[1:]
        return '/'.join(parts) or parsed.path

    @staticmethod
    def _pinimg_resolution_score(url: str) -> int:
        parsed = urllib.parse.urlparse(url or '')
        parts = [p for p in parsed.path.split('/') if p]
        if not parts:
            return 0
        first = parts[0].lower()
        if first == 'originals':
            return 100000
        m = re.match(r'(\d+)x(\d+)?', first)
        if m:
            return int(m.group(1))
        return 0

    @staticmethod
    def _walk_json(node):
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from PinterestService._walk_json(value)
        elif isinstance(node, list):
            for item in node:
                yield from PinterestService._walk_json(item)

    @staticmethod
    def _pick_best_image_url(node: dict) -> str:
        if not isinstance(node, dict):
            return ''
        candidates = []
        for key in ('orig', 'images', 'imageSpec_orig', 'image_cover_url', 'image_medium_url', 'image_url', 'url'):
            value = node.get(key)
            if isinstance(value, dict):
                for subkey in ('url', 'url_https'):
                    if isinstance(value.get(subkey), str):
                        candidates.append(value[subkey])
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        candidates.append(item)
                    elif isinstance(item, dict):
                        for subkey in ('url', 'url_https'):
                            if isinstance(item.get(subkey), str):
                                candidates.append(item[subkey])
            elif isinstance(value, str):
                candidates.append(value)
        pinimg = [c for c in candidates if 'pinimg.com' in c]
        if not pinimg:
            return ''
        return sorted(pinimg, key=PinterestService._pinimg_resolution_score, reverse=True)[0]

    @classmethod
    def _extract_api_data(cls, payloads: list, pin_id: str) -> dict:
        best = {
            'author': '',
            'avatar': '',
            'title': '',
            'description': '',
            'poster': '',
            'images': [],
            'author_candidates': [],
            'avatar_candidates': [],
        }
        image_best = {}
        target = str(pin_id)

        for payload in payloads:
            for node in cls._walk_json(payload):
                node_id = str(node.get('id', ''))
                node_pin_id = str(node.get('pin_id', ''))
                is_target_pin = target and (node_id == target or node_pin_id == target)

                if is_target_pin:
                    best['title'] = (
                        node.get('title')
                        or node.get('grid_title')
                        or node.get('seo_description')
                        or best['title']
                    )
                    best['description'] = (
                        node.get('description')
                        or node.get('rich_summary', {}).get('display_description', '')
                        or best['description']
                    )
                    poster = cls._pick_best_image_url(node)
                    if poster:
                        best['poster'] = poster

                    for key in ('images', 'image_list', 'carousel_data', 'story_pin_data'):
                        value = node.get(key)
                        if isinstance(value, dict):
                            for sub in cls._walk_json(value):
                                img = cls._pick_best_image_url(sub)
                                if img:
                                    image_best[cls._pinimg_canonical_key(img)] = max(
                                        image_best.get(cls._pinimg_canonical_key(img), ''),
                                        img,
                                        key=cls._pinimg_resolution_score,
                                    )
                        elif isinstance(value, list):
                            for item in value:
                                if isinstance(item, dict):
                                    img = cls._pick_best_image_url(item)
                                    if img:
                                        image_best[cls._pinimg_canonical_key(img)] = max(
                                            image_best.get(cls._pinimg_canonical_key(img), ''),
                                            img,
                                            key=cls._pinimg_resolution_score,
                                        )

                    pinner = node.get('pinner') or node.get('creator') or {}
                    if isinstance(pinner, dict):
                        candidate_author = (
                            pinner.get('full_name')
                            or pinner.get('first_name')
                            or pinner.get('username')
                            or ''
                        )
                        if candidate_author and candidate_author not in best['author_candidates']:
                            best['author_candidates'].append(candidate_author)
                        best['author'] = candidate_author or best['author']
                        avatar = cls._pick_best_image_url(pinner) or cls._pick_best_image_url(pinner.get('image_medium', {}))
                        if avatar:
                            if avatar not in best['avatar_candidates']:
                                best['avatar_candidates'].append(avatar)
                            best['avatar'] = avatar

                # Also scan user objects globally for a better avatar once author is known.
                if best['author'] and not best['avatar']:
                    full_name = str(node.get('full_name', '') or node.get('name', '')).strip()
                    username = str(node.get('username', '')).strip()
                    if full_name == best['author'] or username == best['author']:
                        avatar = cls._pick_best_image_url(node)
                        if avatar:
                            if avatar not in best['avatar_candidates']:
                                best['avatar_candidates'].append(avatar)
                            best['avatar'] = avatar

        if best['poster']:
            image_best[cls._pinimg_canonical_key(best['poster'])] = max(
                image_best.get(cls._pinimg_canonical_key(best['poster']), ''),
                best['poster'],
                key=cls._pinimg_resolution_score,
            )
        best['images'] = [url for url in image_best.values() if url]
        return best

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

                const creatorLink =
                    document.querySelector('[data-test-id="creator-link"]') ||
                    document.querySelector('a[href*="/_created/"]');
                const authorText =
                    text('[data-test-id="creator-link"]') ||
                    text('a[href*="/_created/"]') ||
                    '';
                const jsonLdAuthor =
                    (jsonLd.author && (jsonLd.author.name || jsonLd.author.alternateName)) ||
                    '';
                const author = authorText || jsonLdAuthor;

                const avatarCandidates = unique([
                    creatorLink?.querySelector('img')?.currentSrc,
                    document.querySelector('[data-test-id="profile-image"] img')?.currentSrc,
                    document.querySelector('a[href*="/_created/"] img')?.currentSrc,
                    ...(jsonLd.author && jsonLd.author.image
                        ? [Array.isArray(jsonLd.author.image) ? jsonLd.author.image[0] : jsonLd.author.image]
                        : [])
                ]);
                const avatar = avatarCandidates.find(Boolean) || '';

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
                    author_from_dom: authorText,
                    author_from_jsonld: jsonLdAuthor,
                    avatar,
                    avatar_explicit: avatarCandidates.length > 0,
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
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/123.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1440, 'height': 1800},
                locale='en-US',
            )
            page = await context.new_page()
            await page.route(
                '**/*',
                lambda route: route.continue_()
                if route.request.resource_type in ['document', 'script', 'xhr', 'fetch', 'media']
                else route.abort()
            )

            media_urls = []
            json_payloads = []

            async def handle_response(response):
                try:
                    content_type = (response.headers.get('content-type') or '').lower()
                    if 'video/' in content_type and response.url not in media_urls:
                        media_urls.append(response.url)
                    elif 'application/json' in content_type and 'pinterest' in response.url:
                        body = await response.text()
                        if body and len(body) < 2_000_000:
                            try:
                                json_payloads.append(json.loads(body))
                            except Exception:
                                pass
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
        data['json_payloads'] = json_payloads
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

    @staticmethod
    def _file_md5(path: Path) -> str:
        digest = hashlib.md5()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                digest.update(chunk)
        return digest.hexdigest()

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

        api_meta = self._extract_api_data(meta.get('json_payloads', []), pin_id)

        title = (api_meta.get('title') or meta.get('title') or '').strip()
        description = (api_meta.get('description') or meta.get('description') or '').strip()
        description_author = self._extract_author_from_description(description)
        author_from_dom = (meta.get('author_from_dom') or '').strip()
        author_from_jsonld = (meta.get('author_from_jsonld') or '').strip()
        author_name = (
            author_from_dom
            or description_author
            or author_from_jsonld
            or 'Pinterest User'
        )
        api_author = (api_meta.get('author') or '').strip()
        avatar_url = ''
        if api_author and author_name != 'Pinterest User' and api_author == author_name:
            avatar_url = (api_meta.get('avatar') or '').strip()
        if not avatar_url and author_from_dom and meta.get('avatar_explicit'):
            avatar_url = (meta.get('avatar') or '').strip()
        if not avatar_url and author_from_jsonld and author_name == author_from_jsonld and meta.get('avatar_explicit'):
            avatar_url = (meta.get('avatar') or '').strip()
        poster_url = (api_meta.get('poster') or meta.get('poster') or '').strip()

        info(f'[Pinterest] Author: {author_name}')
        info(f'[Pinterest] Avatar URL: {avatar_url or "not found"}')

        video_url = (meta.get('video') or '').strip()
        if not video_url:
            for candidate in meta.get('captured_videos', []):
                if '.mp4' in candidate or 'video' in candidate:
                    video_url = candidate
                    break

        best_by_key = {}
        for candidate in ([poster_url] if poster_url else []) + list(api_meta.get('images', [])) + list(meta.get('images', [])):
            if not candidate or candidate == avatar_url or 'profile' in candidate:
                continue
            key = self._pinimg_canonical_key(candidate)
            prev = best_by_key.get(key)
            if prev is None or self._pinimg_resolution_score(candidate) > self._pinimg_resolution_score(prev):
                best_by_key[key] = candidate
        image_urls = list(best_by_key.values())
        if image_urls:
            image_urls = [max(image_urls, key=self._pinimg_resolution_score)]

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
        seen_hashes = set()
        _safe_title = re.sub(r"(?m)^#", r"\#", title or "Pinterest Pin")
        md_lines = [f'# {_safe_title}', '']
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
                    image_hash = self._file_md5(images_dir / image_name)
                    if image_hash in seen_hashes:
                        (images_dir / image_name).unlink(missing_ok=True)
                        continue
                    seen_hashes.add(image_hash)
                    md_lines.extend([f'![Pinterest image {idx}](images/{image_name})', ''])
                    media_count += 1
                except Exception as e:
                    warning(f'[Pinterest] Image download failed: {image_url} ({e})')

        if avatar_url:
            try:
                self._download_file(avatar_url, post_dir / 'avatar.jpg', normalized_url)
                avatar_hash = self._file_md5(post_dir / 'avatar.jpg')
                if avatar_hash in seen_hashes:
                    (post_dir / 'avatar.jpg').unlink(missing_ok=True)
                    warning('[Pinterest] Avatar matched a content image, discarded as duplicate')
                else:
                    info(f'[Pinterest] Avatar downloaded: {avatar_url}')
            except Exception as e:
                warning(f'[Pinterest] Avatar download failed: {e}')
        else:
            warning('[Pinterest] No avatar URL found')

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
            'avatar_url': avatar_url,
        }

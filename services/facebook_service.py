import asyncio
import json
import os
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from utils.realtime_logger import info, warning, success


class FacebookServiceError(Exception):
    pass


class FacebookService:
    """Facebook post downloader using Playwright."""

    _DOMAIN_RE = re.compile(
        r'https?://(?:www\.|m\.)?(?:facebook\.com|fb\.com)',
        re.IGNORECASE,
    )

    _URL_RE = re.compile(
        r'https?://(?:www\.|m\.)?(?:facebook\.com|fb\.com)/[\w./?=&%#+~:-]+',
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
    def is_valid_facebook_url(cls, url: str) -> bool:
        return bool(cls._DOMAIN_RE.search(url or ''))

    @classmethod
    def extract_url_from_share_text(cls, text: str) -> str:
        m = cls._URL_RE.search(text or '')
        return m.group(0).rstrip('/') if m else ''

    @staticmethod
    def _extract_post_id(url: str) -> str:
        """Extract a post identifier from a Facebook URL."""
        # /posts/<id>
        m = re.search(r'/posts/(\d+)', url)
        if m:
            return m.group(1)
        # story_fbid=<id>
        m = re.search(r'story_fbid=(\d+)', url)
        if m:
            return m.group(1)
        # /photo?fbid=<id> or fbid=<id>
        m = re.search(r'fbid=(\d+)', url)
        if m:
            return m.group(1)
        # /videos/<id>
        m = re.search(r'/videos/(\d+)', url)
        if m:
            return m.group(1)
        # /reel/<id>
        m = re.search(r'/reel/(\d+)', url)
        if m:
            return m.group(1)
        # ?v=<id>
        m = re.search(r'[?&]v=(\d+)', url)
        if m:
            return m.group(1)
        # share link: /share/p/<id> or /share/v/<id> or /share/r/<id>
        m = re.search(r'/share/[prv]/([\w-]+)', url)
        if m:
            return m.group(1)
        return ''

    @staticmethod
    def _extract_username(url: str) -> str:
        """Try to extract a username/page name from a Facebook URL."""
        m = re.search(r'facebook\.com/([^/?#]+)/(?:posts|videos|photos|reels)', url)
        if m and m.group(1) not in ('share', 'permalink.php', 'photo', 'watch', 'groups'):
            return m.group(1)
        m = re.search(r'facebook\.com/profile\.php\?id=(\d+)', url)
        if m:
            return m.group(1)
        return ''

    async def _fetch_post_async(self, url: str) -> dict:
        """Use Playwright to scrape a Facebook post."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
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

            meta = {
                'text': '',
                'author_name': '',
                'author_username': self._extract_username(url) or self._extract_post_id(url) or 'facebook',
                'avatar_url': '',
                'images': [],
                'videos': [],
                'post_id': self._extract_post_id(url) or url.split('/')[-1].split('?')[0],
                'canonical_url': url,
            }

            # Intercept network requests to capture video mp4 URLs
            intercepted_videos: list[str] = []
            seen_video_bases: set[str] = set()

            def _on_request(request):
                u = request.url
                if '.mp4' in u and 'fbcdn' in u:
                    base = re.sub(r'\?.*$', '', u)
                    if base not in seen_video_bases:
                        seen_video_bases.add(base)
                        intercepted_videos.append(u)

            page.on('request', _on_request)

            try:
                info(f'[Facebook] Navigating to {url}')
                await page.goto(url, wait_until='networkidle', timeout=40000)
                await asyncio.sleep(2)

                # Capture final URL after redirect
                final_url = page.url
                meta['canonical_url'] = final_url

                # Re-extract IDs from the final redirected URL
                final_id = self._extract_post_id(final_url)
                if final_id:
                    meta['post_id'] = final_id
                final_uname = self._extract_username(final_url)
                if final_uname:
                    meta['author_username'] = final_uname

                # Open Graph / JSON-LD metadata
                og_data = await page.evaluate('''() => {
                    const get = (name) => {
                        const el = document.querySelector(
                            `meta[property="${name}"], meta[name="${name}"]`);
                        return el ? el.getAttribute('content') : '';
                    };
                    const jsonLd = Array.from(
                            document.querySelectorAll('script[type="application/ld+json"]'))
                        .map(s => { try { return JSON.parse(s.textContent); } catch { return null; } })
                        .filter(Boolean);
                    return {
                        title: get('og:title'),
                        description: get('og:description'),
                        jsonLd,
                    };
                }''')

                if og_data.get('description'):
                    meta['text'] = og_data['description']
                if og_data.get('title'):
                    meta['author_name'] = og_data['title']

                # JSON-LD: richer structured data
                for item in og_data.get('jsonLd', []):
                    if not isinstance(item, dict):
                        continue
                    if item.get('@type') in ('SocialMediaPosting', 'Article', 'NewsArticle'):
                        meta['text'] = item.get('articleBody', meta['text']) or meta['text']
                        author = item.get('author', {})
                        if isinstance(author, dict):
                            meta['author_name'] = author.get('name', meta['author_name'])
                    if item.get('@type') == 'Person':
                        meta['author_name'] = item.get('name', meta['author_name'])

                # DOM text scraping
                dom_text = await page.evaluate('''() => {
                    const SKIP_RE = /^[\\d,\\.\\s·\\u00b7]+$|^\\d[\\d,.]*[KMBkmg]?\\+?$|^(Like|Comment|Share|Follow|Following|More|Send|Reels|Watch|See more|See less|Translate)$/i;
                    // Try Facebook-specific data attributes first
                    const selectors = [
                        '[data-ad-comet-preview="message"]',
                        '[data-ad-preview="message"]',
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el) {
                            const t = (el.innerText || '').trim();
                            if (t.length > 10) return t;
                        }
                    }
                    // Fall back to dir="auto" text, deduplicated, filtered
                    const parts = [];
                    const seen = new Set();
                    Array.from(document.querySelectorAll('[dir="auto"]')).forEach(el => {
                        const t = (el.innerText || '').trim();
                        if (!t || seen.has(t) || t.length < 5) return;
                        if (SKIP_RE.test(t)) return;
                        seen.add(t);
                        parts.push(t);
                    });
                    // Heuristic: the post text is usually the longest unique string
                    if (parts.length) {
                        parts.sort((a, b) => b.length - a.length);
                        return parts[0];
                    }
                    return '';
                }''')

                if dom_text and len(dom_text) > len(meta['text']):
                    meta['text'] = dom_text

                # Images from fbcdn
                images_raw = await page.evaluate('''() => {
                    const SKIP = /t51\\.\\d+-19|[?&]stp=[^&]*_e15_|[?&]stp=dst-jpg_s\\d{2,3}x\\d{2,3}|emoji/;
                    const seen = new Set();
                    const imgs = [];
                    Array.from(document.querySelectorAll('img')).forEach(img => {
                        const src = img.src || '';
                        if (!src || !src.includes('fbcdn')) return;
                        if (SKIP.test(src)) return;
                        const w = img.getBoundingClientRect().width || img.width || 0;
                        if (w < 100) return;
                        const base = src.replace(/\\?.*$/, '');
                        if (!seen.has(base)) { seen.add(base); imgs.push(src); }
                    });
                    return imgs;
                }''')
                meta['images'] = images_raw

                # Videos: DOM + intercepted
                videos_dom = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('video source, video'))
                        .map(v => v.src || v.currentSrc)
                        .filter(s => s && s.startsWith('http'));
                }''')
                seen_vid = set()
                for v in videos_dom + intercepted_videos:
                    base = re.sub(r'\?.*$', '', v)
                    if base not in seen_vid:
                        seen_vid.add(base)
                        meta['videos'].append(v)

                # Avatar
                if not meta['author_username'] or meta['author_username'] == 'facebook':
                    pass
                avatar = await page.evaluate('''() => {
                    const imgs = Array.from(document.querySelectorAll('img[alt]'));
                    const av = imgs.find(img => {
                        const alt = (img.alt || '').toLowerCase();
                        return (alt.includes('profile') || alt.includes('avatar') ||
                                alt.includes("'s profile picture") ||
                                img.src.includes('t51') && img.src.includes('-19')) &&
                               img.src.includes('fbcdn');
                    });
                    return av ? av.src : '';
                }''')
                meta['avatar_url'] = avatar or ''

                # Download images via browser context (CDN URLs are session-signed)
                img_bytes_list = []
                for img_url in meta['images']:
                    try:
                        data = await page.evaluate('''async (url) => {
                            const resp = await fetch(url, {credentials: "include"});
                            if (!resp.ok) return null;
                            const buf = await resp.arrayBuffer();
                            return Array.from(new Uint8Array(buf));
                        }''', img_url)
                        img_bytes_list.append(bytes(data) if data else None)
                    except Exception as exc:
                        warning(f'[Facebook] In-browser image fetch failed: {exc}')
                        img_bytes_list.append(None)
                meta['image_bytes'] = img_bytes_list

                info(f'[Facebook] Scraped: text={len(meta["text"])}ch, '
                     f'images={len(meta["images"])}, videos={len(meta["videos"])}')

            except Exception as exc:
                warning(f'[Facebook] Playwright scrape error: {exc}')
            finally:
                await browser.close()

        return meta

    def _download_file(self, url: str, dest: Path, label: str = '') -> bool:
        if not url:
            return False
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0.0.0 Safari/537.36'
                    ),
                    'Referer': 'https://www.facebook.com/',
                },
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                dest.write_bytes(resp.read())
            info(f'[Facebook] Downloaded {label}: {dest.name}')
            return True
        except Exception as exc:
            warning(f'[Facebook] Failed to download {label}: {exc}')
            return False

    @staticmethod
    def _generate_thumbnail(video_path: Path, save_dir: Path) -> bool:
        if not shutil.which('ffmpeg'):
            return False
        thumbnails_dir = save_dir / 'thumbnails'
        thumbnails_dir.mkdir(exist_ok=True)
        thumb = thumbnails_dir / (video_path.stem + '_thumb.jpg')
        if thumb.exists():
            return True
        try:
            result = subprocess.run(
                ['ffmpeg', '-y', '-i', str(video_path), '-ss', '00:00:01',
                 '-vframes', '1', '-q:v', '2', str(thumb)],
                capture_output=True, timeout=30,
            )
            return result.returncode == 0 and thumb.exists()
        except Exception:
            return False

    def save_post(self, url: str) -> dict:
        """Download and save a Facebook post."""
        meta = asyncio.run(self._fetch_post_async(url))
        post_id = meta['post_id']
        author_username = meta['author_username']

        if not post_id:
            raise FacebookServiceError(f'Could not extract post ID from URL: {url}')

        save_time = datetime.now()
        safe_title = re.sub(r'[^\w\u4e00-\u9fa5]+', '_', meta['text'])[:40].strip('_') or post_id
        folder_name = f"{save_time.strftime('%Y-%m-%d')}_{safe_title}_{post_id}"

        if self.create_date_folders:
            post_dir = (self.base_path / save_time.strftime('%Y')
                        / save_time.strftime('%m') / folder_name)
        else:
            post_dir = self.base_path / folder_name

        post_dir.mkdir(parents=True, exist_ok=True)

        # Avatar
        self._download_file(meta['avatar_url'], post_dir / 'avatar.jpg', 'avatar')

        # Images
        images_dir = post_dir / 'images'
        downloaded_images = 0
        image_bytes_list = meta.get('image_bytes', [])
        if meta['images']:
            images_dir.mkdir(exist_ok=True)
            for i, img_url in enumerate(meta['images'], 1):
                dest = images_dir / f'image_{i:03d}.jpg'
                img_bytes = image_bytes_list[i - 1] if i - 1 < len(image_bytes_list) else None
                if img_bytes and len(img_bytes) > 5000:
                    dest.write_bytes(img_bytes)
                    info(f'[Facebook] Saved image {i} ({len(img_bytes)} bytes) from browser')
                    downloaded_images += 1
                elif self._download_file(img_url, dest, f'image {i}'):
                    downloaded_images += 1

        # Videos
        videos_dir = post_dir / 'videos'
        downloaded_videos = 0
        if meta['videos']:
            videos_dir.mkdir(exist_ok=True)
            for i, vid_url in enumerate(meta['videos'], 1):
                vid_path = videos_dir / f'video_{i:03d}.mp4'
                if self._download_file(vid_url, vid_path, f'video {i}'):
                    downloaded_videos += 1
                    self._generate_thumbnail(vid_path, post_dir)

        media_count = downloaded_images + downloaded_videos

        # content.md
        text = meta['text']
        content_lines = []
        if text:
            content_lines.append(re.sub(r'(?m)^#', r'\\#', text))
            content_lines.append('')
        for i in range(1, downloaded_images + 1):
            content_lines.append(f'![image {i}](images/image_{i:03d}.jpg)')
        if downloaded_images:
            content_lines.append('')
        for i in range(1, downloaded_videos + 1):
            content_lines.append(f'[Video {i}](videos/video_{i:03d}.mp4)')
        (post_dir / 'content.md').write_text('\n'.join(content_lines), encoding='utf-8')

        # content.txt (for FTS)
        (post_dir / 'content.txt').write_text(text, encoding='utf-8')

        # metadata.json
        title_text = text[:100] if text else f'Facebook post {post_id}'
        metadata = {
            'post_id': post_id,
            'url': meta['canonical_url'],
            'author_username': author_username,
            'author_name': meta['author_name'],
            'text': text,
            'title': title_text,
            'images': meta['images'],
            'videos': meta['videos'],
            'saved_at': save_time.isoformat(),
        }
        (post_dir / 'metadata.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        success(f'[Facebook] Saved post {post_id} by {author_username} → {post_dir}')

        return {
            'post_id': post_id,
            'save_path': str(post_dir),
            'author_username': author_username,
            'author_name': meta['author_name'],
            'tweet_text': text[:500],
            'media_count': media_count,
            'title': title_text,
        }

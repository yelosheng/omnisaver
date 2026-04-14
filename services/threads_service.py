import asyncio
import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from utils.realtime_logger import info, warning, success


class ThreadsServiceError(Exception):
    pass


class ThreadsService:
    """Threads (threads.com) post downloader using Playwright."""

    _URL_RE = re.compile(
        r'https?://(?:www\.)?threads\.(?:com|net)/@([\w._]+)/post/([\w-]+)',
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
    def is_valid_threads_url(cls, url: str) -> bool:
        return bool(cls._URL_RE.search(url or ''))

    @classmethod
    def extract_url_from_share_text(cls, text: str) -> str:
        m = cls._URL_RE.search(text or '')
        if not m:
            return ''
        return f'https://www.threads.com/@{m.group(1)}/post/{m.group(2)}'

    @classmethod
    def extract_post_id(cls, url: str) -> str:
        m = cls._URL_RE.search(url or '')
        return m.group(2) if m else ''

    @classmethod
    def extract_username(cls, url: str) -> str:
        m = cls._URL_RE.search(url or '')
        return m.group(1) if m else ''

    async def _fetch_post_async(self, url: str) -> dict:
        """Use Playwright to scrape a Threads post page."""
        post_id = self.extract_post_id(url)
        username = self.extract_username(url)
        clean_url = f'https://www.threads.com/@{username}/post/{post_id}'

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) '
                    'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
                ),
                viewport={'width': 390, 'height': 844},
                locale='en-US',
            )
            page = await context.new_page()

            meta = {
                'text': '',
                'author_name': username,
                'author_username': username,
                'avatar_url': '',
                'images': [],
                'videos': [],
                'post_id': post_id,
            }

            try:
                info(f'[Threads] Navigating to {clean_url}')
                await page.goto(clean_url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(4)

                # Try Open Graph meta tags
                og_data = await page.evaluate('''() => {
                    const get = (name) => {
                        const el = document.querySelector(`meta[property="${name}"], meta[name="${name}"]`);
                        return el ? el.getAttribute('content') : '';
                    };
                    const jsonLd = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                        .map(s => { try { return JSON.parse(s.textContent); } catch { return null; } })
                        .filter(Boolean);
                    return {
                        title: get('og:title'),
                        description: get('og:description'),
                        image: get('og:image'),
                        jsonLd,
                    };
                }''')

                if og_data.get('description'):
                    meta['text'] = og_data['description']

                # Parse author display name from title "Author on Threads"
                if og_data.get('title'):
                    title_match = re.match(r'^(.+?)\s+on Threads', og_data['title'])
                    if title_match:
                        meta['author_name'] = title_match.group(1)

                # Try JSON-LD
                for item in og_data.get('jsonLd', []):
                    if isinstance(item, dict):
                        if item.get('@type') == 'SocialMediaPosting':
                            meta['text'] = item.get('articleBody', meta['text'])
                            author = item.get('author', {})
                            if isinstance(author, dict):
                                meta['author_name'] = author.get('name', meta['author_name'])
                        if item.get('@type') == 'Person':
                            meta['author_name'] = item.get('name', meta['author_name'])
                            meta['avatar_url'] = item.get('image', meta['avatar_url'])

                # Fallback: DOM text scraping
                if not meta['text']:
                    text_content = await page.evaluate('''() => {
                        const selectors = [
                            '[data-pressable-container] span',
                            'article span',
                            'h1',
                            '[dir="auto"]',
                        ];
                        for (const sel of selectors) {
                            const els = Array.from(document.querySelectorAll(sel));
                            const texts = els.map(e => e.innerText.trim()).filter(t => t.length > 20);
                            if (texts.length) return texts[0];
                        }
                        return '';
                    }''')
                    meta['text'] = text_content or ''

                # Images
                images = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('img'))
                        .filter(img => {
                            const src = img.src || '';
                            const w = img.naturalWidth || img.width || 0;
                            return src && w > 100 && !src.includes('emoji') &&
                                   (src.includes('fbcdn') || src.includes('cdninstagram'));
                        })
                        .map(img => img.src);
                }''')
                seen = set()
                for img in images:
                    base = re.sub(r'\?.*$', '', img)
                    if base not in seen:
                        seen.add(base)
                        meta['images'].append(img)

                # Videos
                videos = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('video source, video'))
                        .map(v => v.src || v.currentSrc)
                        .filter(s => s && s.startsWith('http'));
                }''')
                meta['videos'] = list(set(videos))

                # Avatar fallback
                if not meta['avatar_url']:
                    avatar = await page.evaluate('''() => {
                        const imgs = Array.from(document.querySelectorAll('img[alt]'));
                        const av = imgs.find(img => {
                            const alt = (img.alt || '').toLowerCase();
                            return alt.includes('profile') || alt.includes('avatar') ||
                                   (img.width <= 60 && img.src.includes('fbcdn'));
                        });
                        return av ? av.src : '';
                    }''')
                    meta['avatar_url'] = avatar or ''

                info(f'[Threads] Scraped: text={len(meta["text"])}ch, '
                     f'images={len(meta["images"])}, videos={len(meta["videos"])}')

            except Exception as exc:
                warning(f'[Threads] Playwright scrape error: {exc}')
            finally:
                await browser.close()

        return meta

    def _download_file(self, url: str, dest: Path, label: str = '') -> bool:
        if not url:
            return False
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15'},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                dest.write_bytes(resp.read())
            info(f'[Threads] Downloaded {label}: {dest.name}')
            return True
        except Exception as exc:
            warning(f'[Threads] Failed to download {label}: {exc}')
            return False

    def save_post(self, url: str) -> dict:
        """Download and save a Threads post. Returns result dict for process_threads_task."""
        meta = asyncio.run(self._fetch_post_async(url))
        post_id = meta['post_id']
        author_username = meta['author_username']

        save_time = datetime.now()
        safe_title = re.sub(r'[^\w\u4e00-\u9fa5]+', '_', meta['text'])[:40].strip('_') or post_id
        folder_name = f"{save_time.strftime('%Y-%m-%d')}_{safe_title}_{post_id}"

        if self.create_date_folders:
            post_dir = self.base_path / save_time.strftime('%Y') / save_time.strftime('%m') / folder_name
        else:
            post_dir = self.base_path / folder_name

        post_dir.mkdir(parents=True, exist_ok=True)

        # Avatar
        self._download_file(meta['avatar_url'], post_dir / 'avatar.jpg', 'avatar')

        # Images
        images_dir = post_dir / 'images'
        downloaded_images = 0
        if meta['images']:
            images_dir.mkdir(exist_ok=True)
            for i, img_url in enumerate(meta['images'], 1):
                if self._download_file(img_url, images_dir / f'image_{i:03d}.jpg', f'image {i}'):
                    downloaded_images += 1

        # Videos
        videos_dir = post_dir / 'videos'
        downloaded_videos = 0
        if meta['videos']:
            videos_dir.mkdir(exist_ok=True)
            for i, vid_url in enumerate(meta['videos'], 1):
                if self._download_file(vid_url, videos_dir / f'video_{i:03d}.mp4', f'video {i}'):
                    downloaded_videos += 1

        media_count = downloaded_images + downloaded_videos

        # metadata.json
        metadata = {
            'post_id': post_id,
            'url': url,
            'author_username': author_username,
            'author_name': meta['author_name'],
            'text': meta['text'],
            'title': meta['text'][:100] if meta['text'] else f'Threads post by @{author_username}',
            'images': meta['images'],
            'videos': meta['videos'],
            'saved_at': save_time.isoformat(),
        }
        (post_dir / 'metadata.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        # content.md
        content_lines = []
        if meta['text']:
            escaped = re.sub(r'(?m)^#', r'\\#', meta['text'])
            content_lines.append(escaped)
            content_lines.append('')
        for i in range(1, downloaded_images + 1):
            content_lines.append(f'![image {i}](images/image_{i:03d}.jpg)')
        if downloaded_images:
            content_lines.append('')
        for i in range(1, downloaded_videos + 1):
            content_lines.append(f'[Video {i}](videos/video_{i:03d}.mp4)')
        if downloaded_videos:
            content_lines.append('')

        (post_dir / 'content.md').write_text('\n'.join(content_lines), encoding='utf-8')

        success(f'[Threads] Saved post {post_id} by @{author_username} → {post_dir}')

        return {
            'post_id': post_id,
            'save_path': str(post_dir),
            'author_username': author_username,
            'author_name': meta['author_name'],
            'tweet_text': meta['text'][:500],
            'media_count': media_count,
            'title': metadata['title'],
        }

import asyncio
import html
import json
import os
import re
import shutil
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests

from utils.realtime_logger import info, success, warning


class RedditServiceError(Exception):
    pass


class RedditService:
    """Reddit post downloader service using Reddit's public JSON endpoints."""

    _URL_RE = re.compile(
        r'https?://(?:www\.|old\.|m\.)?reddit\.com/r/[\w_]+/comments/([a-z0-9]+)(?:/[^\s?#]*)?(?:[?#][^\s]*)?'
        r'|https?://redd\.it/([a-z0-9]+)(?:[?#][^\s]*)?',
        re.IGNORECASE,
    )
    _SHARE_RE = re.compile(
        r'https?://(?:www\.|old\.|m\.)?reddit\.com/(?:r/[\w_]+/)?s/([A-Za-z0-9]+)(?:[?#][^\s]*)?',
        re.IGNORECASE,
    )
    _UA = 'OmniSaver/1.0 (Reddit save service)'
    _COOKIES_PATH = os.path.expanduser('~/.agent-reach/reddit/cookies.json')
    _BROWSER_UA = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/123.0.0.0 Safari/537.36'
    )

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir) / 'saved_tweets')
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': self._UA})
        self.browser_session = requests.Session()
        self.browser_session.headers.update({
            'User-Agent': self._BROWSER_UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Upgrade-Insecure-Requests': '1',
        })
        self.media_session = requests.Session()
        self.media_session.headers.update({
            'User-Agent': self._BROWSER_UA,
            'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self._rdt_credential = None
        self.client_id = (os.environ.get('REDDIT_CLIENT_ID') or '').strip()
        self.client_secret = (os.environ.get('REDDIT_CLIENT_SECRET') or '').strip()
        self._oauth_token = ''
        self._oauth_session = None

    @classmethod
    def is_valid_reddit_url(cls, url: str) -> bool:
        stripped = (url or '').strip()
        return bool(stripped and (cls._URL_RE.search(stripped) or cls._SHARE_RE.search(stripped)))

    @classmethod
    def extract_url_from_share_text(cls, text: str) -> str:
        text = text or ''
        m = cls._URL_RE.search(text) or cls._SHARE_RE.search(text)
        return m.group(0).rstrip(').,!?') if m else ''

    @classmethod
    def extract_post_id(cls, url: str) -> str:
        m = cls._URL_RE.search(url or '')
        if not m:
            return ''
        return m.group(1) or m.group(2) or ''

    @classmethod
    def is_share_url(cls, url: str) -> bool:
        return bool(url and cls._SHARE_RE.search(url.strip()))

    def _fetch_json(self, url: str, session: requests.Session = None) -> dict:
        response = (session or self.session).get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    @classmethod
    def get_cookies_path(cls) -> str:
        return cls._COOKIES_PATH

    @classmethod
    def load_cookie_file(cls) -> list:
        path = cls.get_cookies_path()
        if not os.path.exists(path):
            return []
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []

    def _import_rdt_modules(self):
        try:
            from rdt_cli.auth import get_credential, save_credential, Credential
            from rdt_cli.client import RedditClient
            return get_credential, save_credential, Credential, RedditClient
        except ImportError:
            repo_root = Path(__file__).resolve().parent.parent
            for site_packages in repo_root.glob('venv/lib/python*/site-packages'):
                site_path = str(site_packages)
                if site_path not in sys.path:
                    sys.path.append(site_path)
            from rdt_cli.auth import get_credential, save_credential, Credential
            from rdt_cli.client import RedditClient
            return get_credential, save_credential, Credential, RedditClient

    def _credential_from_cookie_file(self):
        cookies = self.load_cookie_file()
        if not cookies:
            return None
        cookie_map = {
            c['name']: c['value']
            for c in cookies
            if isinstance(c, dict) and c.get('name') and 'value' in c
        }
        if not cookie_map:
            return None
        _, save_credential, Credential, _ = self._import_rdt_modules()
        cred = Credential(
            cookies=cookie_map,
            source='agent-reach:reddit',
            modhash=cookie_map.get('modhash') or cookie_map.get('csrf_token'),
        )
        try:
            save_credential(cred)
        except Exception:
            pass
        return cred

    def _get_rdt_credential(self):
        if self._rdt_credential is not None:
            return self._rdt_credential
        cred = self._credential_from_cookie_file()
        if cred is None:
            get_credential, _, _, _ = self._import_rdt_modules()
            cred = get_credential()
        self._rdt_credential = cred
        return self._rdt_credential

    def _sync_rdt_cookies(self) -> None:
        cred = self._get_rdt_credential()
        if not cred:
            return
        for name, value in (cred.cookies or {}).items():
            if value:
                self.session.cookies.set(name, value)
                self.browser_session.cookies.set(name, value)

    def _is_blocked_response(self, response: requests.Response) -> bool:
        text = response.text or ''
        return (
            response.status_code in (401, 403, 429)
            or 'blocked by network security' in text.lower()
            or 'use your developer token' in text.lower()
        )

    def _get_oauth_session(self) -> requests.Session:
        if self._oauth_session and self._oauth_token:
            return self._oauth_session
        if not self.client_id or not self.client_secret:
            raise RedditServiceError(
                'Reddit anonymous access is blocked. Set REDDIT_CLIENT_ID and '
                'REDDIT_CLIENT_SECRET, then retry.'
            )

        token_response = self.session.post(
            'https://www.reddit.com/api/v1/access_token',
            auth=(self.client_id, self.client_secret),
            data={'grant_type': 'client_credentials'},
            headers={'User-Agent': self._UA},
            timeout=30,
        )
        token_response.raise_for_status()
        token_data = token_response.json()
        access_token = token_data.get('access_token') or ''
        if not access_token:
            raise RedditServiceError('Failed to obtain Reddit OAuth access token')

        self._oauth_token = access_token
        self._oauth_session = requests.Session()
        self._oauth_session.headers.update({
            'Authorization': f'bearer {access_token}',
            'User-Agent': self._UA,
        })
        return self._oauth_session

    def _fetch_listing(self, post_id: str) -> list:
        try:
            cred = self._get_rdt_credential()
            _, _, _, RedditClient = self._import_rdt_modules()
            with RedditClient(cred) as client:
                return client.get_post_comments(post_id=post_id, limit=25)
        except Exception as e:
            warning(f'[Reddit] rdt-cli fetch failed, falling back: {e}')

        public_url = f'https://www.reddit.com/comments/{post_id}.json?raw_json=1'
        response = self.session.get(public_url, timeout=30)
        if response.ok:
            return response.json()
        if not self._is_blocked_response(response):
            response.raise_for_status()

        oauth_session = self._get_oauth_session()
        oauth_url = f'https://oauth.reddit.com/comments/{post_id}.json?raw_json=1'
        oauth_response = oauth_session.get(oauth_url, timeout=30)
        oauth_response.raise_for_status()
        return oauth_response.json()

    def _resolve_share_url(self, url: str) -> str:
        if not self.is_share_url(url):
            return url

        self._sync_rdt_cookies()
        candidates = [url]
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.startswith('www.'):
            candidates.append(parsed._replace(netloc=parsed.netloc[4:]).geturl())
        else:
            candidates.append(parsed._replace(netloc=f'www.{parsed.netloc}').geturl())

        for candidate in candidates:
            try:
                response = self.browser_session.get(candidate, timeout=30, allow_redirects=True)
                resolved = response.url or candidate
                if self.is_valid_reddit_url(resolved) and self.extract_post_id(resolved):
                    info(f'[Reddit] Resolved share URL: {url} -> {resolved}')
                    return resolved
                response.raise_for_status()
            except Exception as e:
                warning(f'[Reddit] Share URL resolve failed: {candidate} ({e})')

        resolved = self._resolve_share_url_playwright(url)
        if resolved != url:
            info(f'[Reddit] Resolved share URL via Playwright: {url} -> {resolved}')
            return resolved

        return url

    def _resolve_share_url_playwright(self, url: str) -> str:
        async def _run() -> str:
            try:
                from playwright.async_api import async_playwright
            except Exception:
                return url

            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context(
                        user_agent=self._BROWSER_UA,
                        viewport={'width': 1440, 'height': 900},
                    )
                    page = await context.new_page()
                    await page.goto(url, wait_until='domcontentloaded', timeout=45000)
                    await page.wait_for_timeout(2000)
                    current = page.url or url
                    if self.extract_post_id(current):
                        await browser.close()
                        return current
                    for selector in ('link[rel="canonical"]', 'meta[property="og:url"]'):
                        handle = await page.query_selector(selector)
                        if handle:
                            value = await handle.get_attribute('href' if selector.startswith('link') else 'content')
                            if value and self.extract_post_id(value):
                                await browser.close()
                                return value
                    await browser.close()
            except Exception as e:
                warning(f'[Reddit] Playwright share resolve failed: {url} ({e})')
            return url

        try:
            return asyncio.run(_run())
        except Exception as e:
            warning(f'[Reddit] Playwright share resolve failed: {url} ({e})')
            return url

    def _canonical_post_url(self, post: dict, post_id: str) -> str:
        permalink = post.get('permalink') or ''
        if permalink:
            return urllib.parse.urljoin('https://www.reddit.com', permalink)
        return f'https://www.reddit.com/comments/{post_id}/'

    def _fetch_avatar(self, username: str) -> str:
        if not username:
            return ''
        try:
            cred = self._get_rdt_credential()
            _, _, _, RedditClient = self._import_rdt_modules()
            with RedditClient(cred) as client:
                user = client.get_user_about(username)
            avatar = user.get('snoovatar_img') or user.get('icon_img') or ''
            if avatar:
                return avatar.split('?')[0]
        except Exception as e:
            warning(f'[Reddit] rdt-cli avatar fetch failed for {username}: {e}')

        try:
            url = f'https://www.reddit.com/user/{username}/about.json?raw_json=1'
            response = self.session.get(url, timeout=30)
            if response.ok:
                data = response.json()
            elif self._is_blocked_response(response):
                oauth_session = self._get_oauth_session()
                data = self._fetch_json(f'https://oauth.reddit.com/user/{username}/about.json?raw_json=1', oauth_session)
            else:
                response.raise_for_status()
            user = data.get('data', {})
            avatar = user.get('snoovatar_img') or user.get('icon_img') or ''
            if avatar:
                return avatar.split('?')[0]
        except Exception as e:
            warning(f'[Reddit] Avatar fetch failed for {username}: {e}')
        return ''

    @staticmethod
    def _sanitize(text: str) -> str:
        return re.sub(r'[^\w\u4e00-\u9fff\- ]+', ' ', (text or '')).strip()[:40] or 'reddit_post'

    @staticmethod
    def _rewrite_media_url(url: str) -> str:
        if not url:
            return ''
        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or '').lower()
        if host == 'preview.redd.it':
            path = parsed.path or ''
            if path:
                return urllib.parse.urlunparse(parsed._replace(netloc='i.redd.it'))
        return url

    @staticmethod
    def _media_dedupe_key(url: str) -> str:
        parsed = urllib.parse.urlparse(url or '')
        host = (parsed.netloc or '').lower()
        path = parsed.path or ''
        if host in ('i.redd.it', 'preview.redd.it'):
            return f'i.redd.it:{path}'
        if host == 'external-preview.redd.it':
            return f'external-preview:{path}?{parsed.query}'
        return f'{host}:{path}?{parsed.query}'

    @staticmethod
    def _is_reddit_media_host(host: str) -> bool:
        return host in ('i.redd.it', 'preview.redd.it', 'external-preview.redd.it')

    def _build_media_candidate_urls(self, url: str) -> list[str]:
        if not url:
            return []

        candidates = []

        def _add(candidate: str):
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or '').lower()
        rewritten = self._rewrite_media_url(url)

        _add(url)
        _add(rewritten)

        if self._is_reddit_media_host(host) and parsed.query:
            stripped = urllib.parse.urlunparse(parsed._replace(query='', fragment=''))
            _add(stripped)
            _add(self._rewrite_media_url(stripped))

        if host == 'i.redd.it':
            preview = urllib.parse.urlunparse(parsed._replace(netloc='preview.redd.it'))
            _add(preview)
            if parsed.query:
                _add(urllib.parse.urlunparse(parsed._replace(netloc='preview.redd.it', query='', fragment='')))
        elif host == 'preview.redd.it':
            direct = urllib.parse.urlunparse(parsed._replace(netloc='i.redd.it'))
            _add(direct)
            if parsed.query:
                _add(urllib.parse.urlunparse(parsed._replace(netloc='i.redd.it', query='', fragment='')))

        return candidates

    def _get_media_request(self, url: str, referer: str) -> tuple[requests.Session, dict]:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or '').lower()
        if self._is_reddit_media_host(host):
            headers = {}
            if referer:
                headers['Referer'] = referer
            return self.media_session, headers

        self._sync_rdt_cookies()
        return self.browser_session, {
            'Referer': referer,
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-Mode': 'no-cors',
            'Sec-Fetch-Dest': 'image',
        }

    def _download_file(self, url: str, dest: Path, referer: str = 'https://www.reddit.com/'):
        last_error = None
        for candidate in self._build_media_candidate_urls(url):
            try:
                session, headers = self._get_media_request(candidate, referer)
                response = session.get(
                    candidate,
                    timeout=60,
                    stream=True,
                    headers=headers,
                )
                response.raise_for_status()
                content_type = (response.headers.get('Content-Type') or '').lower()
                if 'text/html' in content_type:
                    raise RedditServiceError(f'Unexpected HTML response for media URL: {candidate}')
                with open(dest, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                return
            except Exception as e:
                last_error = e
        if last_error:
            raise last_error

    def _collect_image_urls(self, post: dict) -> list[str]:
        urls = []

        if post.get('is_gallery') and isinstance(post.get('media_metadata'), dict):
            gallery_order = post.get('gallery_data', {}).get('items', [])
            for item in gallery_order:
                media_id = item.get('media_id')
                meta = post['media_metadata'].get(media_id, {})
                s = meta.get('s', {})
                u = s.get('u') or s.get('gif')
                if u:
                    urls.append(self._rewrite_media_url(html.unescape(u)))

        direct = post.get('url_overridden_by_dest') or post.get('url') or ''
        if direct and re.search(r'(i\.redd\.it|preview\.redd\.it|external-preview\.redd\.it).+\.(jpg|jpeg|png|webp)', direct, re.I):
            urls.append(self._rewrite_media_url(direct))

        preview_images = post.get('preview', {}).get('images', [])
        for image in preview_images:
            source = image.get('source', {})
            u = source.get('url')
            if u:
                urls.append(html.unescape(u))

        deduped = []
        seen = set()
        for url in urls:
            key = self._media_dedupe_key(url)
            if key not in seen:
                seen.add(key)
                deduped.append(url)
        return deduped

    def save_post(self, url: str) -> dict:
        if not self.is_valid_reddit_url(url):
            raise RedditServiceError(f'Invalid Reddit URL: {url}')

        url = self._resolve_share_url(url)
        post_id = self.extract_post_id(url)
        if not post_id:
            raise RedditServiceError(f'Could not extract Reddit post ID from: {url}')

        info(f'[Reddit] Fetching post {post_id}')
        listing = self._fetch_listing(post_id)
        if not isinstance(listing, list) or not listing or not listing[0].get('data', {}).get('children'):
            raise RedditServiceError(f'Reddit JSON did not contain post data for: {url}')

        post = listing[0]['data']['children'][0]['data']
        canonical_url = self._canonical_post_url(post, post_id)
        title = html.unescape(post.get('title') or 'Reddit Post')
        body = html.unescape(post.get('selftext') or '').strip()
        author = post.get('author') or 'reddit'
        subreddit = post.get('subreddit_name_prefixed') or f"r/{post.get('subreddit', '')}".rstrip('/')

        save_time = datetime.now()
        folder_name = f'{save_time.strftime("%Y-%m-%d")}_{self._sanitize(title)}_{post_id}'
        if self.create_date_folders:
            post_dir = self.base_path / save_time.strftime('%Y') / save_time.strftime('%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        media_count = 0
        _safe_title = re.sub(r"(?m)^#", r"\#", title)
        md_lines = [f'# {_safe_title}', '']
        md_lines.append(f'**作者**: u/{author}  ')
        md_lines.append(f'**版块**: {subreddit}  ')
        md_lines.append(f'**来源**: {canonical_url}  ')
        md_lines.append('')

        video_url = ''
        if post.get('is_video'):
            video_url = ((post.get('secure_media') or {}).get('reddit_video') or {}).get('fallback_url', '')
            if video_url:
                video_url = video_url.split('?')[0]
                videos_dir = post_dir / 'videos'
                videos_dir.mkdir(exist_ok=True)
                try:
                    self._download_file(video_url, videos_dir / 'video.mp4')
                    md_lines.extend(['[视频](videos/video.mp4)', ''])
                    media_count += 1
                except Exception as e:
                    warning(f'[Reddit] Video download failed: {e}')

        image_urls = self._collect_image_urls(post)
        if image_urls:
            images_dir = post_dir / 'images'
            images_dir.mkdir(exist_ok=True)
            for idx, image_url in enumerate(image_urls, start=1):
                ext = Path(urllib.parse.urlparse(image_url).path).suffix.lower() or '.jpg'
                filename = f'{idx}{ext}'
                try:
                    self._download_file(image_url, images_dir / filename)
                    md_lines.extend([f'![Reddit image {idx}](images/{filename})', ''])
                    media_count += 1
                except Exception as e:
                    warning(f'[Reddit] Image download failed: {image_url} ({e})')

        thumb = post.get('thumbnail')
        if thumb and isinstance(thumb, str) and thumb.startswith('http'):
            thumbs_dir = post_dir / 'thumbnails'
            thumbs_dir.mkdir(exist_ok=True)
            try:
                self._download_file(thumb, thumbs_dir / 'cover.jpg')
            except Exception as e:
                warning(f'[Reddit] Thumbnail download failed: {e}')

        avatar_url = self._fetch_avatar(author)
        if avatar_url:
            try:
                self._download_file(avatar_url, post_dir / 'avatar.jpg')
            except Exception as e:
                warning(f'[Reddit] Avatar download failed: {e}')

        if body:
            md_lines.extend(['---', '', re.sub(r'(?m)^#', r'\#', body)])
        (post_dir / 'content.md').write_text('\n'.join(md_lines).strip() + '\n', encoding='utf-8')
        (post_dir / 'content.txt').write_text(body or title, encoding='utf-8')
        (post_dir / 'metadata.json').write_text(
            json.dumps(
                {
                    'id': post_id,
                    'title': title,
                    'description': body[:500],
                    'author': author,
                    'subreddit': subreddit,
                    'url': canonical_url,
                    'platform': 'reddit',
                    'saved_at': save_time.isoformat(),
                    'video_url': video_url,
                    'image_count': len(image_urls),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding='utf-8',
        )

        success(f'[Reddit] Post saved to {post_dir}')
        return {
            'post_id': post_id,
            'title': title,
            'save_path': str(post_dir),
            'author_username': author,
            'author_name': author,
            'tweet_text': (body or title)[:500],
            'media_count': media_count,
        }

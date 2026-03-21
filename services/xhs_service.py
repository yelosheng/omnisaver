import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from utils.realtime_logger import info, error, warning, success

# Ensure npm global bin and pyenv bin are in PATH so mcporter and yt-dlp are findable
_EXTRA_PATH_DIRS = [
    os.path.expanduser('~/.npm-global/bin'),
    os.path.expanduser('~/.pyenv/shims'),
    os.path.expanduser('~/.pyenv/versions/3.11.9/bin'),
]
for _p in _EXTRA_PATH_DIRS:
    if _p not in os.environ.get('PATH', ''):
        os.environ['PATH'] = _p + ':' + os.environ.get('PATH', '')


class XHSServiceError(Exception):
    pass


class XHSService:
    """XiaoHongShu post downloader service."""

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir) / 'saved_tweets')
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    # ------------------------------------------------------------------
    # URL parsing
    # ------------------------------------------------------------------

    @staticmethod
    def extract_url_from_share_text(text: str) -> str:
        """Extract a XHS or xhslink URL from mobile app share text.

        The share text format looks like:
            放只龟进去，就变龟缸了~ http://xhslink.com/o/37WXzj3a3B 复制后打开【小红书】查看笔记！

        Returns the first xhslink.com or xiaohongshu.com URL found, or the
        original text stripped if no match (so callers can still try validation).
        """
        m = re.search(r'https?://(?:xhslink\.com|(?:www\.)?xiaohongshu\.com)/\S+', text)
        return m.group(0).rstrip('，。！,.') if m else text.strip()

    @staticmethod
    def resolve_xhslink(url: str) -> str:
        """Follow xhslink.com short URL redirects and return the final URL."""
        if 'xhslink.com' not in url:
            return url
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0'},
            method='HEAD',
        )
        # Don't follow — capture Location header manually so we get the real URL
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        # Use a simple approach: follow up to 5 redirects manually
        current = url
        for _ in range(5):
            try:
                r = urllib.request.urlopen(
                    urllib.request.Request(current, headers={'User-Agent': 'Mozilla/5.0'}),
                    timeout=10,
                )
                final = r.url
                if final and final != current:
                    current = final
                break
            except Exception:
                break
        return current

    @staticmethod
    def is_valid_xhs_url(url: str) -> bool:
        return bool(re.search(
            r'https?://(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item)/[a-f0-9]+',
            url
        ))

    @staticmethod
    def normalize_xhs_url(url: str) -> str:
        """Convert /discovery/item/<id> to /explore/<id> keeping query params."""
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.rstrip('/')
        if '/discovery/item/' in path:
            feed_id = path.split('/')[-1]
            path = f'/explore/{feed_id}'
            parsed = parsed._replace(path=path)
            url = urllib.parse.urlunparse(parsed)
        return url

    @staticmethod
    def parse_url(url: str) -> tuple[str, str]:
        """Return (feed_id, xsec_token) from a full XHS URL."""
        parsed = urllib.parse.urlparse(url)
        feed_id = parsed.path.rstrip('/').split('/')[-1]
        params = urllib.parse.parse_qs(parsed.query)
        xsec_token = params.get('xsec_token', [''])[0]
        return feed_id, xsec_token

    # ------------------------------------------------------------------
    # Favorites (收藏) via Playwright
    # ------------------------------------------------------------------

    _COOKIES_PATH = os.path.expanduser('~/.agent-reach/xhs/cookies.json')

    def get_favorites(self, user_id: str = None) -> list[dict]:
        """Scrape 我的收藏 page and return {feed_id, xsec_token, url} for each post.

        Requires Playwright and valid XHS cookies at ~/.agent-reach/xhs/cookies.json.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise XHSServiceError('playwright not installed — run: pip install playwright && playwright install chromium')

        if not os.path.exists(self._COOKIES_PATH):
            raise XHSServiceError(f'XHS cookies not found at {self._COOKIES_PATH}')

        cookies_list = json.loads(Path(self._COOKIES_PATH).read_text())

        # Resolve user_id from cookies if not provided
        if not user_id:
            # Try to read from saved metadata or use a known default
            web_session = next((c for c in cookies_list if c.get('name') == 'web_session'), None)
            if not web_session:
                raise XHSServiceError('Cannot determine user_id — please pass it explicitly')

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            ctx.add_cookies([{
                'name': c['name'], 'value': c['value'],
                'domain': c.get('domain', '.xiaohongshu.com'),
                'path': c.get('path', '/'),
            } for c in cookies_list if isinstance(c, dict)])

            page = ctx.new_page()
            uid = user_id or ''
            collect_url = f'https://www.xiaohongshu.com/user/profile/{uid}/collect' if uid else 'https://www.xiaohongshu.com/user/profile/me/collect'
            page.goto(collect_url, timeout=30000)
            import time as _time
            _time.sleep(5)

            # Extract all /explore/<id>?xsec_token=... links
            links = page.query_selector_all('a[href*="/explore/"]')
            seen = set()
            feeds = []
            for link in links:
                href = link.get_attribute('href') or ''
                if 'xsec_token' not in href:
                    continue
                full = f'https://www.xiaohongshu.com{href}' if href.startswith('/') else href
                feed_id, xsec_token = self.parse_url(full)
                if feed_id and feed_id not in seen:
                    seen.add(feed_id)
                    feeds.append({'feed_id': feed_id, 'xsec_token': xsec_token, 'url': full})

            browser.close()

        info(f'Found {len(feeds)} favorites on 收藏 page')
        return feeds

    # ------------------------------------------------------------------
    # Feed list (home feed) — kept for reference
    # ------------------------------------------------------------------

    def get_feed_list(self) -> list[dict]:
        """Fetch home feed. Returns list of {feed_id, xsec_token, url}."""
        result = subprocess.run(
            ['mcporter', 'call', 'xiaohongshu.list_feeds()'],
            capture_output=True, text=True, timeout=90
        )
        if result.returncode != 0:
            raise XHSServiceError(f'mcporter error: {result.stderr.strip()}')
        data = json.loads(result.stdout)
        feeds = []
        for item in data.get('feeds', []):
            feed_id = item.get('id', '')
            xsec_token = item.get('xsecToken', '')
            if feed_id:
                url = f'https://www.xiaohongshu.com/explore/{feed_id}?xsec_token={xsec_token}'
                feeds.append({'feed_id': feed_id, 'xsec_token': xsec_token, 'url': url})
        return feeds

    # ------------------------------------------------------------------
    # Core fetch
    # ------------------------------------------------------------------

    def _get_post(self, feed_id: str, xsec_token: str) -> dict:
        result = subprocess.run(
            ['mcporter', 'call',
             f'xiaohongshu.get_feed_detail(feed_id: "{feed_id}", xsec_token: "{xsec_token}")'],
            capture_output=True, text=True, timeout=90
        )
        if result.returncode != 0:
            raise XHSServiceError(f'mcporter error: {result.stderr.strip()}')
        return json.loads(result.stdout)

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize(name: str) -> str:
        return re.sub(r'[\\/:*?"<>|]', '_', name).strip()[:60]

    @staticmethod
    def _download_image(url: str, path: Path):
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            path.write_bytes(resp.read())

    @staticmethod
    def _download_video(post_url: str, output_dir: Path):
        # Download to /tmp first to avoid NAS I/O errors during ffmpeg merge
        tmp_dir = tempfile.mkdtemp(prefix='xhs_dl_')
        try:
            result = subprocess.run(
                ['yt-dlp', '-o', os.path.join(tmp_dir, 'video.%(ext)s'),
                 '--no-playlist', '--merge-output-format', 'mp4', post_url],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                raise XHSServiceError(f'yt-dlp failed: {result.stderr.strip()[:200]}')
            # Move downloaded file(s) to final output_dir
            for fname in os.listdir(tmp_dir):
                shutil.move(os.path.join(tmp_dir, fname), str(output_dir / fname))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def save_post(self, url: str) -> dict:
        """
        Download a XiaoHongShu post and save it locally.

        Files are saved in a Twitter-compatible layout so the web frontend
        can display them:
          content.txt     — plain-text post description
          content.md      — richer markdown version
          metadata.json   — full API response (no comments)
          avatar.jpg      — author profile picture
          images/         — image posts: 01.webp, 02.webp, …
          videos/         — video posts: <title>.mp4
          thumbnails/     — video posts: cover.webp

        Returns:
            dict with keys: feed_id, title, type, save_path, image_count,
                            author_username, author_name, tweet_text
        """
        url = self.normalize_xhs_url(url)

        if not self.is_valid_xhs_url(url):
            raise XHSServiceError(f'Invalid XiaoHongShu URL: {url}')

        feed_id, xsec_token = self.parse_url(url)
        if not xsec_token:
            raise XHSServiceError('xsec_token missing from URL')

        info(f'Fetching XHS post {feed_id}...')
        data = self._get_post(feed_id, xsec_token)
        note = data['data']['note']
        post_type = note.get('type', 'normal')

        title = note.get('title') or 'untitled'
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        folder_name = f'{date_str}_{feed_id}'
        if self.create_date_folders:
            post_dir = self.base_path / now.strftime('%Y') / now.strftime('%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        user = note.get('user', {})
        interact = note.get('interactInfo', {})
        ts = note.get('time', 0)
        post_date = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M') if ts else 'unknown'
        desc = note.get('desc', '')
        author_username = user.get('userId', '') or user.get('id', '')
        author_name = user.get('nickname', '') or user.get('nickName', '')

        # metadata.json (no comments)
        clean = {k: v for k, v in note.items() if k not in ('comments', 'commentList')}
        (post_dir / 'metadata.json').write_text(
            json.dumps(clean, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        # content.txt — plain text for frontend preview
        (post_dir / 'content.txt').write_text(desc, encoding='utf-8')

        # content.md — richer markdown
        md = '\n'.join([
            f"# {note.get('title', '')}",
            '',
            f"**作者**: {author_name}  ",
            f"**发布时间**: {post_date}  ",
            f"**IP归属**: {note.get('ipLocation', '')}  ",
            f"**类型**: {'视频' if post_type == 'video' else '图文'}  ",
            f"**点赞**: {interact.get('likedCount', '')}  "
            f"**收藏**: {interact.get('collectedCount', '')}  "
            f"**评论**: {interact.get('commentCount', '')}",
            '',
            '---',
            '',
            desc,
            '',
            '---',
            '',
            f'**链接**: {url}',
        ])
        (post_dir / 'content.md').write_text(md, encoding='utf-8')

        # avatar.jpg — author profile picture
        avatar_url = user.get('avatar', '') or user.get('avatarUrl', '')
        if avatar_url:
            try:
                self._download_image(avatar_url, post_dir / 'avatar.jpg')
            except Exception as e:
                warning(f'Avatar download failed: {e}')

        images = note.get('imageList', [])
        image_count = 0
        media_count = 0

        if post_type == 'video':
            # Cover → thumbnails/cover.webp
            if images:
                cover_url = images[0].get('urlDefault') or images[0].get('urlPre', '')
                if cover_url:
                    try:
                        thumbnails_dir = post_dir / 'thumbnails'
                        thumbnails_dir.mkdir(exist_ok=True)
                        self._download_image(cover_url, thumbnails_dir / 'cover.webp')
                        success('Cover image saved')
                        image_count = 1
                    except Exception as e:
                        warning(f'Cover image failed: {e}')
            # Video → videos/<title>.mp4
            info('Downloading video...')
            videos_dir = post_dir / 'videos'
            videos_dir.mkdir(exist_ok=True)
            self._download_video(url, videos_dir)
            success('Video saved')
            media_count = image_count + len(list(videos_dir.glob('*.mp4')))
        else:
            # Images → images/01.webp, 02.webp, …
            if images:
                img_dir = post_dir / 'images'
                img_dir.mkdir(exist_ok=True)
                for i, img in enumerate(images):
                    img_url = img.get('urlDefault') or img.get('urlPre', '')
                    if not img_url:
                        continue
                    try:
                        self._download_image(img_url, img_dir / f'{i+1:02d}.webp')
                        image_count += 1
                    except Exception as e:
                        warning(f'Image {i+1} failed: {e}')
            media_count = image_count

        success(f'XHS post saved to {post_dir}')
        return {
            'feed_id': feed_id,
            'title': title,
            'type': post_type,
            'save_path': str(post_dir),
            'image_count': image_count,
            'media_count': media_count,
            'author_username': author_username,
            'author_name': author_name,
            'tweet_text': desc,
        }

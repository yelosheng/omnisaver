import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from utils.realtime_logger import info, warning, success

# Ensure pyenv yt-dlp is on PATH
_EXTRA_PATH_DIRS = [
    os.path.expanduser('~/.pyenv/shims'),
    os.path.expanduser('~/.pyenv/versions/3.11.9/bin'),
    os.path.expanduser('~/.npm-global/bin'),
]
for _p in _EXTRA_PATH_DIRS:
    if _p not in os.environ.get('PATH', ''):
        os.environ['PATH'] = _p + ':' + os.environ.get('PATH', '')


class YoutubeServiceError(Exception):
    pass


class YoutubeService:
    """YouTube video downloader service."""

    _URL_RE = re.compile(
        r'https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/)|youtu\.be/)'
        r'([A-Za-z0-9_-]{11})'
    )

    def __init__(self, base_path: str = None, create_date_folders: bool = True,
                 youtube_api_key: str = None):
        if base_path is None:
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir) / 'saved_tweets')
        self.base_path = Path(base_path)
        self.youtube_api_key = youtube_api_key
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    @classmethod
    def is_valid_youtube_url(cls, url: str) -> bool:
        return bool(cls._URL_RE.search(url))

    @classmethod
    def extract_video_id(cls, url: str) -> str:
        m = cls._URL_RE.search(url)
        return m.group(1) if m else ''

    @staticmethod
    def normalize_url(url: str) -> str:
        """Return canonical watch URL."""
        m = re.search(r'([A-Za-z0-9_-]{11})', url)
        if m:
            return f'https://www.youtube.com/watch?v={m.group(1)}'
        return url

    # ------------------------------------------------------------------
    # VTT → plain text
    # ------------------------------------------------------------------

    @staticmethod
    def _vtt_to_text(vtt_path: Path) -> str:
        """Parse a VTT subtitle file into clean readable text."""
        import re as _re
        lines = vtt_path.read_text(encoding='utf-8', errors='replace').splitlines()
        segments = []
        in_cue = False
        buf = []
        timestamp_re = _re.compile(r'^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->')
        for line in lines:
            line = line.strip()
            if timestamp_re.match(line):
                in_cue = True
                if buf:
                    segments.append(' '.join(buf))
                    buf = []
            elif in_cue and line and not line.startswith('NOTE') and not line.isdigit():
                # Strip inline tags like <00:00:01.000><c>text</c>
                clean = _re.sub(r'<[^>]+>', '', line).strip()
                if clean:
                    buf.append(clean)
            elif not line:
                if buf:
                    segments.append(' '.join(buf))
                    buf = []
                in_cue = False
        if buf:
            segments.append(' '.join(buf))

        # Deduplicate overlapping auto-generated caption segments
        deduped = []
        for seg in segments:
            if not deduped or seg != deduped[-1]:
                # Also skip if current segment is fully contained in the previous
                if not deduped or not deduped[-1].endswith(seg):
                    deduped.append(seg)

        return '\n'.join(deduped)

    # ------------------------------------------------------------------
    # Avatar fetch
    # ------------------------------------------------------------------

    def _fetch_channel_avatar(self, channel_id: str, post_dir: Path) -> None:
        """Download channel avatar via YouTube Data API v3 and save as avatar.jpg."""
        if not self.youtube_api_key or not channel_id:
            return
        try:
            import urllib.request
            api_url = (
                f'https://www.googleapis.com/youtube/v3/channels'
                f'?part=snippet&id={channel_id}&key={self.youtube_api_key}'
            )
            with urllib.request.urlopen(api_url, timeout=10) as resp:
                data = json.loads(resp.read())
            items = data.get('items', [])
            if not items:
                return
            thumb_url = (items[0].get('snippet', {})
                         .get('thumbnails', {})
                         .get('default', {})
                         .get('url', ''))
            if not thumb_url:
                return
            avatar_path = post_dir / 'avatar.jpg'
            urllib.request.urlretrieve(thumb_url, str(avatar_path))
            info(f'Channel avatar saved for {channel_id}')
        except Exception as e:
            warning(f'Could not fetch channel avatar: {e}')

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def save_video(self, url: str) -> dict:
        """
        Download a YouTube video and save it locally.

        Layout (same convention as XHS/WeChat):
          content.txt      — plain text description
          content.md       — markdown with metadata header
          metadata.json    — full yt-dlp info dict (trimmed)
          videos/          — video.mp4
          thumbnails/      — cover.jpg
          subtitles/       — *.vtt subtitle files (if available)

        Returns dict with: video_id, title, channel, save_path,
                           author_username, author_name, tweet_text
        """
        if not self.is_valid_youtube_url(url):
            raise YoutubeServiceError(f'Invalid YouTube URL: {url}')

        url = self.normalize_url(url)
        video_id = self.extract_video_id(url)
        info(f'Fetching YouTube metadata: {url}')

        # --- metadata ---
        meta_result = subprocess.run(
            ['yt-dlp', '--dump-json', '--no-playlist',
             '--remote-components', 'ejs:github', url],
            capture_output=True, text=True, timeout=60
        )
        if meta_result.returncode != 0:
            raise YoutubeServiceError(
                f'yt-dlp metadata failed: {meta_result.stderr.strip()[:300]}'
            )
        meta = json.loads(meta_result.stdout)

        title = meta.get('title', 'untitled')
        channel = meta.get('channel') or meta.get('uploader', '')
        channel_id = meta.get('channel_id') or meta.get('uploader_id', '')
        description = meta.get('description', '')
        upload_date = meta.get('upload_date', '')  # YYYYMMDD
        view_count = meta.get('view_count', 0)
        like_count = meta.get('like_count', 0)
        duration = meta.get('duration_string') or meta.get('duration', '')

        # Parse upload date for folder naming
        now = datetime.now()
        pub_date = now
        if upload_date and len(upload_date) == 8:
            try:
                pub_date = datetime.strptime(upload_date, '%Y%m%d')
            except ValueError:
                pass

        date_str = pub_date.strftime('%Y-%m-%d')
        folder_name = f'{datetime.now().strftime("%Y-%m-%d")}_{video_id}'
        if self.create_date_folders:
            post_dir = self.base_path / datetime.now().strftime('%Y') / datetime.now().strftime('%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        post_dir.mkdir(parents=True, exist_ok=True)

        # --- download video (to local /tmp first to avoid NAS write errors) ---
        info(f'Downloading video: {title}')
        vid_dir = post_dir / 'videos'
        vid_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='yt_') as tmp_dir:
            tmp_out = os.path.join(tmp_dir, 'video.mp4')
            err_log = os.path.join(tmp_dir, 'stderr.txt')
            with open(err_log, 'w') as _ef:
                dl_result = subprocess.run(
                    ['yt-dlp', '--no-playlist',
                     '--remote-components', 'ejs:github',
                     '--no-continue', '--no-part',
                     '--retries', '10', '--fragment-retries', '10',
                     '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                     '--merge-output-format', 'mp4',
                     '-o', tmp_out,
                     url],
                    stdout=subprocess.DEVNULL, stderr=_ef, timeout=600
                )
            if dl_result.returncode != 0:
                err_text = Path(err_log).read_text(encoding='utf-8', errors='replace')[-500:]
                raise YoutubeServiceError(f'yt-dlp download failed: {err_text}')
            shutil.move(tmp_out, str(vid_dir / 'video.mp4'))

        # --- thumbnail ---
        thumb_dir = post_dir / 'thumbnails'
        thumb_dir.mkdir(exist_ok=True)
        subprocess.run(
            ['yt-dlp', '--skip-download', '--write-thumbnail',
             '--convert-thumbnails', 'jpg',
             '-o', str(thumb_dir / 'cover'),
             url],
            capture_output=True, timeout=30
        )
        # yt-dlp may add extension; find the file
        cover_file = None
        for ext in ('jpg', 'png', 'webp'):
            candidate = thumb_dir / f'cover.{ext}'
            if candidate.exists():
                cover_file = candidate
                break

        # --- subtitles: download in video's original language ---
        video_lang = (meta.get('language') or 'en').split('-')[0]  # e.g. 'en', 'zh', 'ja'
        # Build lang priority: original lang first, then common variants, then en fallback
        lang_priority = [video_lang]
        if video_lang == 'zh':
            lang_priority = ['zh-Hans', 'zh-Hant', 'zh']
        if 'en' not in lang_priority:
            lang_priority.append('en')
        sub_langs = ','.join(lang_priority)

        sub_dir = post_dir / 'subtitles'
        sub_dir.mkdir(exist_ok=True)
        subprocess.run(
            ['yt-dlp', '--skip-download',
             '--write-sub', '--write-auto-sub',
             '--sub-lang', sub_langs,
             '--convert-subs', 'vtt',
             '-o', str(sub_dir / '%(id)s'),
             url],
            capture_output=True, timeout=60
        )
        sub_files = list(sub_dir.glob('*.vtt'))
        if not sub_files:
            sub_dir.rmdir()  # clean up empty dir
        else:
            # Pick the best subtitle file based on language priority
            preferred = None
            for lang in lang_priority:
                matches = [f for f in sub_files if f'.{lang}.' in f.name]
                if matches:
                    preferred = matches[0]
                    break
            if preferred is None:
                preferred = sub_files[0]
            transcript = self._vtt_to_text(preferred)
            if transcript:
                (post_dir / 'transcript.txt').write_text(transcript, encoding='utf-8')

        # --- content.txt ---
        (post_dir / 'content.txt').write_text(description, encoding='utf-8')

        # --- content.md ---
        safe_description = re.sub(r'(?m)^#', r'\#', description)
        safe_title = re.sub(r'^#', r'\#', title)

        md = '\n'.join([
            f'# {safe_title}',
            '',
            f'**频道**: {channel}  ',
            f'**发布时间**: {date_str}  ',
            f'**时长**: {duration}  ',
            f'**观看数**: {view_count:,}  ' if view_count else '',
            f'**点赞数**: {like_count:,}  ' if like_count else '',
            f'**来源**: {url}  ',
            '',
            '[视频](videos/video.mp4)',
            '',
            '---',
            '',
            safe_description,
        ])
        (post_dir / 'content.md').write_text(md, encoding='utf-8')

        # --- metadata.json (trimmed) ---
        keep_keys = {
            'id', 'title', 'description', 'upload_date', 'channel', 'channel_id',
            'uploader', 'uploader_id', 'duration', 'duration_string',
            'view_count', 'like_count', 'comment_count',
            'thumbnail', 'webpage_url', 'tags', 'categories',
        }
        trimmed_meta = {k: v for k, v in meta.items() if k in keep_keys}
        (post_dir / 'metadata.json').write_text(
            json.dumps(trimmed_meta, ensure_ascii=False, indent=2), encoding='utf-8'
        )

        # --- channel avatar ---
        self._fetch_channel_avatar(channel_id, post_dir)

        success(f'YouTube video saved to {post_dir}')
        return {
            'video_id': video_id,
            'title': title,
            'channel': channel,
            'save_path': str(post_dir),
            'author_username': channel_id,
            'author_name': channel,
            'tweet_text': description[:500],
            'duration': str(duration),
        }

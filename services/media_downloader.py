import os
import tempfile
import requests
from typing import List, Optional
from urllib.parse import urlparse
from pathlib import Path
from tqdm import tqdm
from models.media_file import MediaFile
import subprocess
import shutil
from utils.realtime_logger import info, error, warning, success, debug


class MediaDownloadError(Exception):
    """Media download error"""
    pass


class MediaDownloader:
    """Media file downloader"""

    def __init__(self, max_retries: int = 3, timeout: int = 30, chunk_size: int = 8192,
                 twitter_auth_token: Optional[str] = None, twitter_ct0: Optional[str] = None):
        """
        Initialize media downloader

        Args:
            max_retries: Maximum retry attempts
            timeout: Request timeout (seconds)
            chunk_size: Download chunk size (bytes)
            twitter_auth_token: Twitter auth_token cookie (for yt-dlp authenticated video downloads)
            twitter_ct0: Twitter ct0 cookie
        """
        self.max_retries = max_retries
        self.timeout = timeout
        self.chunk_size = chunk_size
        self.twitter_auth_token = twitter_auth_token
        self.twitter_ct0 = twitter_ct0

        # Supported image formats
        self.image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        # Supported video formats
        self.video_extensions = {'.mp4', '.mov', '.avi', '.webm', '.mkv'}
    
    def download_images(self, media_urls: List[str], save_path: str) -> List[MediaFile]:
        """
        Download image files
        
        Args:
            media_urls: List of image URLs
            save_path: Save path
            
        Returns:
            List of successfully downloaded MediaFile objects
        """
        if not media_urls:
            return []
        
        # Ensure save directory exists
        images_dir = os.path.join(save_path, 'images')
        os.makedirs(images_dir, exist_ok=True)
        
        downloaded_files = []
        
        for i, url in enumerate(media_urls, 1):
            try:
                filename = self.get_media_filename(url, i, 'image')
                local_path = os.path.join(images_dir, filename)
                
                info(f"[MediaDownloader] Downloading image {i}/{len(media_urls)}: {filename}")
                
                if self._download_file(url, local_path):
                    media_file = MediaFile(
                        url=url,
                        local_path=local_path,
                        media_type='photo',
                        filename=filename
                    )
                    downloaded_files.append(media_file)
                    success(f"[MediaDownloader] ✓ Downloaded image: {filename}")
                else:
                    error(f"[MediaDownloader] ✗ Failed to download image: {filename}")
                    
            except Exception as e:
                error(f"[MediaDownloader] ✗ Error downloading image {i}: {e}")
                continue
        
        return downloaded_files
    
    def download_videos(self, media_urls: List[str], save_path: str) -> List[MediaFile]:
        """
        Download video files and generate thumbnails
        
        Args:
            media_urls: List of video URLs
            save_path: Save path
            
        Returns:
            List of successfully downloaded MediaFile objects
        """
        if not media_urls:
            return []
        
        # Ensure save directory exists
        videos_dir = os.path.join(save_path, 'videos')
        os.makedirs(videos_dir, exist_ok=True)
        
        downloaded_files = []
        _video_exts = {'.mp4', '.webm', '.mkv', '.avi', '.mov', '.m4v'}

        # Pre-group: for Twitter tweet URLs, call yt-dlp ONCE per unique URL so
        # yt-dlp can download all videos in the tweet together (avoids --playlist-items
        # issues where different videos in the same tweet use different stream formats).
        # Each unique tweet URL maps to the ordered list of global slot indices.
        _twitter_slots: dict = {}   # tweet_url -> [i, ...]
        _non_twitter: list = []     # [(i, url), ...]
        for i, url in enumerate(media_urls, 1):
            if ('x.com' in url or 'twitter.com' in url) and '/status/' in url:
                _twitter_slots.setdefault(url, []).append(i)
            else:
                _non_twitter.append((i, url))

        # ── Twitter videos: one yt-dlp call per unique tweet URL ──────────────
        # Download to a local /tmp directory first to avoid NAS I/O errors
        # during yt-dlp's intermediate .part file writes, then move to final location.
        for tweet_url, indices in _twitter_slots.items():
            local_tmp_dir = None
            try:
                local_tmp_dir = tempfile.mkdtemp(prefix='ytdl_')
                url_key = abs(hash(tweet_url)) % 1000000
                tmp_template = os.path.join(local_tmp_dir, f'_dl{url_key}_%(playlist_index)02d.%(ext)s')
                cmd = ['yt-dlp', '-o', tmp_template, '--merge-output-format', 'mp4']

                cookies_file = None
                if self.twitter_auth_token and self.twitter_ct0:
                    cookies_file = tempfile.NamedTemporaryFile(
                        mode='w', suffix='.txt', delete=False, prefix='yt_cookies_'
                    )
                    cookies_file.write("# Netscape HTTP Cookie File\n")
                    cookies_file.write(f".twitter.com\tTRUE\t/\tTRUE\t0\tauth_token\t{self.twitter_auth_token}\n")
                    cookies_file.write(f".twitter.com\tTRUE\t/\tTRUE\t0\tct0\t{self.twitter_ct0}\n")
                    cookies_file.write(f".x.com\tTRUE\t/\tTRUE\t0\tauth_token\t{self.twitter_auth_token}\n")
                    cookies_file.write(f".x.com\tTRUE\t/\tTRUE\t0\tct0\t{self.twitter_ct0}\n")
                    cookies_file.flush()
                    cookies_file.close()
                    cmd += ['--cookies', cookies_file.name]
                cmd.append(tweet_url)

                info(f"[MediaDownloader] yt-dlp download for tweet (slots {indices}): {tweet_url}")
                result = subprocess.run(cmd, capture_output=True, text=True)
                if cookies_file:
                    try:
                        os.unlink(cookies_file.name)
                    except OSError:
                        pass
                if result.returncode != 0:
                    raise Exception(f"Video download failed: yt-dlp exit {result.returncode}: {result.stderr.strip()[:300]}")

                # Collect downloaded files from local tmp dir, sorted (playlist order)
                tmp_files = sorted([
                    f for f in os.listdir(local_tmp_dir)
                    if f.startswith(f'_dl{url_key}_')
                    and not f.endswith(('.part', '.ytdl'))
                    and os.path.splitext(f)[1].lower() in _video_exts
                    and os.path.getsize(os.path.join(local_tmp_dir, f)) > 0
                ])

                # Move files to final NAS location and assign to slots
                for slot_i, tmp_file in zip(indices, tmp_files):
                    final_ext = os.path.splitext(tmp_file)[1]
                    final_filename = f'video_{slot_i:02d}{final_ext}'
                    tmp_path = os.path.join(local_tmp_dir, tmp_file)
                    final_path = os.path.join(videos_dir, final_filename)
                    shutil.move(tmp_path, final_path)
                    media_file = MediaFile(url=tweet_url, local_path=final_path,
                                           media_type='video', filename=final_filename)
                    downloaded_files.append(media_file)
                    success(f"[MediaDownloader] ✓ yt-dlp video: {final_filename}")
                    self._generate_video_thumbnail(final_path, save_path)

                if len(tmp_files) < len(indices):
                    warning(f"[MediaDownloader] Expected {len(indices)} videos from tweet, got {len(tmp_files)}")

            except Exception as e:
                error(f"[MediaDownloader] ✗ yt-dlp error for {tweet_url}: {e}")
            finally:
                # Clean up local tmp dir regardless of success/failure
                if local_tmp_dir and os.path.exists(local_tmp_dir):
                    shutil.rmtree(local_tmp_dir, ignore_errors=True)

        # ── Non-Twitter videos: direct download ───────────────────────────────
        for i, url in _non_twitter:
            try:

                filename = self.get_media_filename(url, i, 'video')
                local_path = os.path.join(videos_dir, filename)

                info(f"[MediaDownloader] Downloading video {i}/{len(media_urls)}: {filename}")

                if self._download_file(url, local_path, show_progress=True):
                    media_file = MediaFile(
                        url=url,
                        local_path=local_path,
                        media_type='video',
                        filename=filename
                    )
                    downloaded_files.append(media_file)
                    success(f"[MediaDownloader] ✓ Downloaded video: {filename}")
                    self._generate_video_thumbnail(local_path, save_path)
                else:
                    error(f"[MediaDownloader] ✗ Failed to download video: {filename}")

            except Exception as e:
                error(f"[MediaDownloader] ✗ Error downloading video {i}: {e}")

        return downloaded_files
    
    def download_avatars(self, avatar_urls: List[str], save_path: str) -> List[MediaFile]:
        """
        Download avatar files
        
        Args:
            avatar_urls: List of avatar URLs
            save_path: Save path
            
        Returns:
            List of successfully downloaded MediaFile objects
        """
        if not avatar_urls:
            return []
        
        # Ensure save directory exists
        os.makedirs(save_path, exist_ok=True)
        
        downloaded_files = []
        
        for i, url in enumerate(avatar_urls, 1):
            try:
                info(f"[MediaDownloader] Downloading avatar {i}/{len(avatar_urls)}: avatar.jpg")
                
                # Avatar fixed naming as avatar.jpg
                filename = "avatar.jpg"
                file_path = os.path.join(save_path, filename)
                
                # Download file
                ok = self._download_file(url, file_path, show_progress=True)
                if ok:
                    # Get file size
                    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

                    # Create MediaFile object for avatar
                    media_file = MediaFile(
                        url=url,
                        local_path=file_path,
                        media_type='photo',  # Avatar is treated as photo
                        filename=filename
                    )
                    downloaded_files.append(media_file)
                    success(f"[MediaDownloader] ✓ Downloaded avatar: {filename} ({file_size} bytes)")
                
            except Exception as e:
                error(f"[MediaDownloader] ✗ Error downloading avatar {i}: {e}")
                continue
        
        return downloaded_files
    
    def get_media_filename(self, url: str, index: int, media_type: str = 'media') -> str:
        """
        Generate media filename
        
        Args:
            url: Media URL
            index: File index
            media_type: Media type ('image', 'video', 'media')
            
        Returns:
            Generated filename
        """
        try:
            parsed_url = urlparse(url)
            path = parsed_url.path
            
            # Try to extract file extension from URL
            original_ext = Path(path).suffix.lower()
            
            # If no extension in URL, set default extension based on media type
            if not original_ext:
                if media_type == 'image':
                    original_ext = '.jpg'
                elif media_type == 'video':
                    original_ext = '.mp4'
                else:
                    original_ext = '.bin'
            
            # Validate if extension is reasonable
            if media_type == 'image' and original_ext not in self.image_extensions:
                original_ext = '.jpg'
            elif media_type == 'video' and original_ext not in self.video_extensions:
                original_ext = '.mp4'
            
            # Generate filename
            filename = f"{media_type}_{index:02d}{original_ext}"
            
            return filename
            
        except Exception:
            # If parsing fails, use default filename
            ext = '.jpg' if media_type == 'image' else '.mp4'
            return f"{media_type}_{index:02d}{ext}"
    
    def _download_file(self, url: str, local_path: str, show_progress: bool = False) -> bool:
        """
        Download single file
        
        Args:
            url: File URL
            local_path: Local save path
            show_progress: Whether to show progress bar
            
        Returns:
            Whether download was successful
        """
        if not url:
            return False
        
        # If file already exists and size is reasonable, skip download
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            info(f"[MediaDownloader] File already exists: {os.path.basename(local_path)}")
            return True
        
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                # Send HEAD request to get file size
                head_response = requests.head(url, timeout=self.timeout)
                total_size = int(head_response.headers.get('content-length', 0))
                
                # Start download
                response = requests.get(url, timeout=self.timeout, stream=True)
                response.raise_for_status()
                
                # Create progress bar
                progress_bar = None
                if show_progress and total_size > 0:
                    progress_bar = tqdm(
                        total=total_size,
                        unit='B',
                        unit_scale=True,
                        desc=os.path.basename(local_path)
                    )
                
                # Write to file
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        if chunk:
                            f.write(chunk)
                            if progress_bar:
                                progress_bar.update(len(chunk))
                
                if progress_bar:
                    progress_bar.close()
                
                # Validate downloaded file
                if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                    return True
                else:
                    raise MediaDownloadError("Downloaded file is empty or corrupted")
                    
            except requests.exceptions.Timeout:
                last_exception = MediaDownloadError(f"Download timeout after {self.timeout} seconds")
            except requests.exceptions.ConnectionError:
                last_exception = MediaDownloadError("Connection error during download")
            except requests.exceptions.HTTPError as e:
                last_exception = MediaDownloadError(f"HTTP error: {e}")
            except Exception as e:
                last_exception = MediaDownloadError(f"Download failed: {e}")
            
            # If not the last attempt, wait and retry
            if attempt < self.max_retries:
                wait_time = 2 ** attempt  # Exponential backoff
                warning(f"[MediaDownloader] Download failed, retrying in {wait_time} seconds... (attempt {attempt + 1}/{self.max_retries + 1})")
                import time
                time.sleep(wait_time)
            
            # Clean up possibly corrupted file
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except OSError:
                    pass
        
        # All retries failed
        if last_exception:
            error(f"[MediaDownloader] Download failed after {self.max_retries + 1} attempts: {last_exception}")
        
        return False
    
    def _generate_video_thumbnail(self, video_path: str, save_path: str) -> bool:
        """
        Generate thumbnail from video using FFmpeg
        
        Args:
            video_path: Path to the video file
            save_path: Directory to save thumbnail
            
        Returns:
            Whether thumbnail generation was successful
        """
        try:
            # Check if FFmpeg is available
            if not shutil.which('ffmpeg'):
                warning("[MediaDownloader] FFmpeg not found, skipping thumbnail generation")
                return False
            
            # Create thumbnails directory
            thumbnails_dir = os.path.join(save_path, 'thumbnails')
            os.makedirs(thumbnails_dir, exist_ok=True)
            
            # Generate thumbnail filename
            video_filename = os.path.basename(video_path)
            thumbnail_name = os.path.splitext(video_filename)[0] + '_thumb.jpg'
            thumbnail_path = os.path.join(thumbnails_dir, thumbnail_name)
            
            # Skip if thumbnail already exists
            if os.path.exists(thumbnail_path):
                info(f"[MediaDownloader] Thumbnail already exists: {thumbnail_name}")
                return True
            
            # FFmpeg command to extract frame at 1 second (or 10th frame)
            # -ss 1: seek to 1 second
            # -vframes 1: extract only 1 frame
            # -q:v 2: high quality
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-ss', '1',  # Extract frame at 1 second
                '-vframes', '1',
                '-q:v', '2',  # High quality
                '-y',  # Overwrite output file
                thumbnail_path
            ]
            
            # Run FFmpeg command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout
            )
            
            if result.returncode == 0 and os.path.exists(thumbnail_path):
                success(f"[MediaDownloader] ✓ Generated thumbnail: {thumbnail_name}")
                return True
            else:
                error(f"[MediaDownloader] ✗ Failed to generate thumbnail: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            error("[MediaDownloader] ✗ Thumbnail generation timed out")
            return False
        except Exception as e:
            error(f"[MediaDownloader] ✗ Error generating thumbnail: {e}")
            return False
    
    def get_file_size(self, url: str) -> Optional[int]:
        """
        Get remote file size
        
        Args:
            url: File URL
            
        Returns:
            File size (bytes), returns None if retrieval fails
        """
        try:
            response = requests.head(url, timeout=self.timeout)
            response.raise_for_status()
            return int(response.headers.get('content-length', 0))
        except Exception:
            return None
    
    def validate_url(self, url: str) -> bool:
        """
        Validate if URL is accessible
        
        Args:
            url: URL to validate
            
        Returns:
            Whether URL is accessible
        """
        try:
            response = requests.head(url, timeout=self.timeout)
            return response.status_code == 200
        except Exception:
            return False
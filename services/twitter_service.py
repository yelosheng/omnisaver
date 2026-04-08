import json
import re
import shutil
import subprocess
from typing import List, Optional, Dict, Any
from datetime import datetime
from models.tweet import Tweet
from utils.url_parser import TwitterURLParser
from services.web_scraper import TwitterWebScraper
from services.playwright_scraper import TwitterPlaywrightScraperSync
from utils.realtime_logger import info, error, warning, success


class TwitterScrapingError(Exception):
    """Twitter Scraping Error"""
    pass


class TwitterService:
    """Twitter Service - Web scraping only"""

    def __init__(self, max_retries: int = 3, timeout: int = 30, use_playwright: bool = True,
                 xreach_auth_token: Optional[str] = None, xreach_ct0: Optional[str] = None):
        """
        Initialize Twitter Service

        Args:
            max_retries: Maximum retry attempts
            timeout: Request timeout in seconds
            use_playwright: Whether to use Playwright for web scraping (default True, recommended)
            xreach_auth_token: Twitter auth_token cookie for xreach (enables logged-in scraping)
            xreach_ct0: Twitter ct0 cookie for xreach
        """
        self.max_retries = max_retries
        self.timeout = timeout
        self.use_playwright = use_playwright
        self.xreach_auth_token = xreach_auth_token
        self.xreach_ct0 = xreach_ct0

        # Check if xreach is available and credentials provided
        self.use_xreach = bool(
            xreach_auth_token and xreach_ct0 and shutil.which('xreach')
        )
        if self.use_xreach:
            info("[TwitterService] xreach available with credentials — will use as primary scraper")

        # Initialize web scraper (fallback)
        if self.use_playwright:
            try:
                self.web_scraper = TwitterPlaywrightScraperSync(headless=True, timeout=timeout, debug=False)
                info("[TwitterService] Using Playwright browser automation scraping")
            except ImportError as e:
                warning(f"[TwitterService] Playwright unavailable, falling back to traditional web scraping: {e}")
                self.web_scraper = TwitterWebScraper(timeout=timeout)
                self.use_playwright = False
        else:
            self.web_scraper = TwitterWebScraper(timeout=timeout)
            info("[TwitterService] Using traditional web scraping")

        info("[TwitterService] Web scraping mode initialized")
    
    def _run_xreach(self, *args) -> Any:
        """Run an xreach command and return parsed JSON output."""
        cmd = [
            'xreach',
            '--auth-token', self.xreach_auth_token,
            '--ct0', self.xreach_ct0,
        ] + list(args) + ['--json']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        if result.returncode != 0:
            raise TwitterScrapingError(f"xreach error: {result.stderr.strip()}")
        return json.loads(result.stdout)

    def _xreach_item_to_tweet(self, item: Dict[str, Any]) -> Tweet:
        """Convert an xreach tweet item dict to a Tweet object."""
        created_at_str = item.get('createdAt', '')
        try:
            created_at = datetime.strptime(created_at_str, '%a %b %d %H:%M:%S %z %Y')
        except (ValueError, AttributeError):
            created_at = datetime.now()

        user = item.get('user', {})
        media = item.get('media', [])
        media_urls = []
        media_types = []

        # Add author avatar first
        avatar_url = user.get('profileImageUrl', '')
        if avatar_url:
            media_urls.append(avatar_url)
            media_types.append('avatar')

        for m in media:
            url = m.get('url', '')
            if not url:
                continue
            mtype = m.get('type', 'photo')
            # xreach returns *_video_thumb (JPEG) for videos, not a real video stream.
            # Replace with the tweet URL so yt-dlp can download the actual video.
            if mtype == 'video' and 'video_thumb' in url:
                screen_name = user.get('screenName', 'i')
                url = f"https://x.com/{screen_name}/status/{item['id']}"
            media_urls.append(url)
            media_types.append(mtype)

        return Tweet(
            id=item['id'],
            text=item.get('text', ''),
            html_content=None,
            author_username=user.get('screenName', ''),
            author_name=user.get('name', ''),
            created_at=created_at,
            media_urls=media_urls,
            media_types=media_types,
            reply_to=item.get('inReplyToTweetId'),
            conversation_id=item.get('conversationId', item['id'])
        )

    def extract_tweet_id(self, url: str) -> str:
        """
        Extract tweet ID from URL
        
        Args:
            url: Twitter URL
            
        Returns:
            Tweet ID
            
        Raises:
            ValueError: Invalid URL
        """
        tweet_id = TwitterURLParser.extract_tweet_id(url)
        if not tweet_id:
            raise ValueError(f"Invalid Twitter URL: {url}")
        return tweet_id
    
    def get_tweet(self, tweet_id_or_url: str) -> Tweet:
        """
        Get single tweet information using web scraping
        
        Args:
            tweet_id_or_url: Tweet ID or full Twitter URL
            
        Returns:
            Tweet object
            
        Raises:
            TwitterScrapingError: Failed to get tweet
            ValueError: Invalid tweet ID
        """
        # Determine if input is URL or tweet ID
        if tweet_id_or_url.startswith('http'):
            # It's a URL
            tweet_url = tweet_id_or_url
            tweet_id = self.extract_tweet_id(tweet_url)
            if not tweet_id:
                raise ValueError(f"Cannot extract tweet ID from URL: {tweet_id_or_url}")
        else:
            # It's a tweet ID
            tweet_id = tweet_id_or_url
            if not tweet_id or not tweet_id.isdigit():
                raise ValueError(f"Invalid tweet ID: {tweet_id}")
            tweet_url = f"https://x.com/i/web/status/{tweet_id}"
        
        # Try xreach first if credentials are configured
        if self.use_xreach:
            try:
                info(f"[TwitterService] Using xreach for tweet {tweet_id}")
                data = self._run_xreach('tweet', tweet_url)
                # xreach tweet returns a single object or a list; normalise to object
                item = data[0] if isinstance(data, list) else data
                if item.get('text') is not None:
                    success(f"[TwitterService] xreach successful for tweet {tweet_id}")
                    return self._xreach_item_to_tweet(item)
            except Exception as e:
                warning(f"[TwitterService] xreach failed for {tweet_id}, falling back to Playwright: {e}")

        # Fallback: web scraping
        try:
            info(f"[TwitterService] Using web scraping for tweet {tweet_id}")
            web_data = self.web_scraper.get_tweet_data(tweet_url)

            if web_data and web_data.get('text'):
                success(f"[TwitterService] Web scraping successful, text length: {len(web_data['text'])}")
                return self._create_tweet_from_web_data(web_data)
            else:
                raise TwitterScrapingError(f"No valid tweet data found for {tweet_id}")

        except Exception as e:
            error(f"[TwitterService] Web scraping failed for {tweet_url}: {e}")
            raise TwitterScrapingError(f"Failed to fetch tweet {tweet_id} from {tweet_url}: {e}")
    
    def _create_tweet_from_web_data(self, web_data: Dict[str, Any]) -> Tweet:
        """
        Create Tweet object from web scraping data
        
        Args:
            web_data: Data returned by web scraping
            
        Returns:
            Tweet object
        """
        # Parse creation time
        created_at_str = web_data.get('created_at', datetime.now().isoformat())
        try:
            if 'T' in created_at_str:
                created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            else:
                created_at = datetime.fromisoformat(created_at_str)
        except (ValueError, AttributeError):
            created_at = datetime.now()
        
        return Tweet(
            id=web_data['id'],
            text=web_data['text'],
            html_content=web_data.get('html_content'),
            author_username=web_data.get('author_username', ''),
            author_name=web_data.get('author_name', ''),
            created_at=created_at,
            media_urls=web_data.get('media_urls', []),
            media_types=web_data.get('media_types', []),
            reply_to=web_data.get('reply_to'),
            conversation_id=web_data.get('conversation_id', web_data['id'])
        )
    
    def _get_article_via_playwright(self, url: str):
        """Use Playwright directly to check for article content. Returns (is_article, Tweet|None)."""
        web_data = self.web_scraper.get_tweet_data(url)
        if web_data and web_data.get('is_article') and web_data.get('text'):
            return True, self._create_tweet_from_web_data(web_data)
        return False, None

    def get_tweet_by_url(self, url: str) -> Tweet:
        """
        Get tweet information by URL
        
        Args:
            url: Twitter URL
            
        Returns:
            Tweet object
            
        Raises:
            TwitterScrapingError: Scraping failed
            ValueError: Invalid URL
        """
        tweet_id = self.extract_tweet_id(url)
        return self.get_tweet(tweet_id)
    
    def get_thread(self, tweet_id: str) -> List[Tweet]:
        if not tweet_id or not tweet_id.isdigit():
            raise ValueError(f"Invalid tweet ID: {tweet_id}")

        if self.use_xreach:
            try:
                info(f"[TwitterService] Using xreach thread for {tweet_id}")
                tweet_url = f"https://x.com/i/web/status/{tweet_id}"
                items = self._run_xreach('thread', tweet_url)
                if isinstance(items, list) and items:
                    # Build a lookup map by tweet id
                    items_by_id = {item['id']: item for item in items if item.get('id')}
                    # Find the root tweet
                    root = items_by_id.get(tweet_id) or items[0]
                    original_author = root.get('user', {}).get('screenName', '')
                    # Follow the self-reply chain: start from root, then find each
                    # tweet where the same author replied directly to the previous one
                    thread_items = [root]
                    current_id = root['id']
                    for _ in range(100):  # cap iterations
                        next_item = next(
                            (item for item in items
                             if item.get('inReplyToTweetId') == current_id
                             and item.get('user', {}).get('screenName') == original_author),
                            None
                        )
                        if next_item is None:
                            break
                        thread_items.append(next_item)
                        current_id = next_item['id']
                    tweets = [self._xreach_item_to_tweet(item) for item in thread_items]
                    tweets.sort(key=lambda t: t.created_at)
                    # If xreach returned a single tweet whose text is mostly/only a URL,
                    # it's likely a Twitter Article tweet — fall back to Playwright which
                    # can detect and extract the full article content.
                    if self.use_playwright:
                        try:
                            status_url = f"https://x.com/i/web/status/{tweet_id}"
                            is_art, pw_tweet = self._get_article_via_playwright(status_url)
                            if is_art and pw_tweet:
                                success(f"[TwitterService] Playwright detected article content for {tweet_id}")
                                return [pw_tweet]
                        except Exception as pw_err:
                            warning(f"[TwitterService] Playwright article check failed: {pw_err}")
                    success(f"[TwitterService] xreach thread returned {len(tweets)} tweets")
                    return tweets
            except Exception as e:
                warning(f"[TwitterService] xreach thread failed for {tweet_id}, falling back: {e}")

        return [self.get_tweet(tweet_id)]

    def get_thread_by_url(self, url: str) -> List[Tweet]:
        """
        Get tweet thread by URL
        
        Args:
            url: Twitter URL
            
        Returns:
            List of tweets sorted by time
            
        Raises:
            TwitterScrapingError: Scraping failed
            ValueError: Invalid URL
        """
        tweet_id = self.extract_tweet_id(url)
        return self.get_thread(tweet_id)
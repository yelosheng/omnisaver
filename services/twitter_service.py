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
    
    def __init__(self, max_retries: int = 3, timeout: int = 30, use_playwright: bool = True):
        """
        Initialize Twitter Service
        
        Args:
            max_retries: Maximum retry attempts
            timeout: Request timeout in seconds
            use_playwright: Whether to use Playwright for web scraping (default True, recommended)
        """
        self.max_retries = max_retries
        self.timeout = timeout
        self.use_playwright = use_playwright
        
        # Initialize web scraper
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
        
        # Use web scraping to get complete data
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
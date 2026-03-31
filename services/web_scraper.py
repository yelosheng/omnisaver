#!/usr/bin/env python3
"""
Twitter web scraping service
For getting complete tweet content, bypassing API limitations
"""

import requests
import re
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import time
from bs4 import BeautifulSoup
from utils.realtime_logger import info, warning, error, success, debug


class TwitterWebScraper:
    """Twitter web scraper"""
    
    def __init__(self, timeout: int = 30):
        """
        Initialize web scraper
        
        Args:
            timeout: Request timeout (seconds)
        """
        self.timeout = timeout
        self.session = requests.Session()
        
        # Set request headers to simulate real browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        })
    
    def extract_tweet_id(self, url: str) -> str:
        """
        Extract tweet ID from URL
        
        Args:
            url: Twitter URL
            
        Returns:
            Tweet ID
        """
        # Support multiple URL formats
        patterns = [
            r'twitter\.com/\w+/status/(\d+)',
            r'x\.com/\w+/status/(\d+)',
            r'mobile\.twitter\.com/\w+/status/(\d+)',
            r'twitter\.com/i/web/status/(\d+)',  # Add support for this format
            r'status/(\d+)',  # Simplified matching
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        raise ValueError(f"Unable to extract tweet ID from URL: {url}")
    
    def get_tweet_content(self, url: str) -> Dict:
        """
        Get tweet content through web scraping
        
        Args:
            url: Twitter URL
            
        Returns:
            Dictionary containing tweet information
        """
        try:
            tweet_id = self.extract_tweet_id(url)
            
            # Convert to standard Twitter URL
            clean_url = f"https://twitter.com/i/web/status/{tweet_id}"
            
            info(f"[WebScraper] Fetching tweet from: {clean_url}")
            
            # Send request
            response = self.session.get(clean_url, timeout=self.timeout)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try to extract tweet data from page
            tweet_data = self._extract_tweet_data(soup, tweet_id)
            
            if not tweet_data:
                # If first method fails, try other methods
                tweet_data = self._extract_from_json_ld(soup, tweet_id)
            
            if not tweet_data:
                # Finally try extracting from meta tags
                tweet_data = self._extract_from_meta_tags(soup, tweet_id)
            
            if not tweet_data:
                raise Exception("Unable to extract tweet data from page")
            
            return tweet_data
            
        except Exception as e:
            error(f"[WebScraper] Error fetching tweet {url}: {e}")
            raise e
    
    def _extract_tweet_data(self, soup: BeautifulSoup, tweet_id: str) -> Optional[Dict]:
        """
        Extract tweet data from HTML
        
        Args:
            soup: BeautifulSoup object
            tweet_id: Tweet ID
            
        Returns:
            Tweet data dictionary or None
        """
        try:
            # Find tweet text
            tweet_text = ""
            
            # Try multiple selectors to find tweet text
            text_selectors = [
                '[data-testid="tweetText"]',
                '.tweet-text',
                '.TweetTextSize',
                '.js-tweet-text',
                '[role="article"] [lang]'
            ]
            
            for selector in text_selectors:
                elements = soup.select(selector)
                if elements:
                    # Merge all found text
                    texts = []
                    for element in elements:
                        text = element.get_text(strip=True)
                        if text and len(text) > 10:  # Filter out text that's too short
                            texts.append(text)
                    
                    if texts:
                        tweet_text = '\n\n'.join(texts)
                        break
            
            # If no tweet text found, try extracting from title
            if not tweet_text:
                title = soup.find('title')
                if title:
                    title_text = title.get_text()
                    # Twitter page title usually contains tweet content
                    if '"' in title_text:
                        # Extract content within quotes
                        match = re.search(r'"([^"]+)"', title_text)
                        if match:
                            tweet_text = match.group(1)
            
            # Extract author information
            author_name = ""
            author_username = ""
            
            # Try to extract author information from meta tags
            author_meta = soup.find('meta', {'name': 'twitter:creator'})
            if author_meta:
                author_username = author_meta.get('content', '').replace('@', '')
            
            # Try to extract author name from page content
            name_selectors = [
                '[data-testid="UserName"]',
                '.fullname',
                '.ProfileHeaderCard-name'
            ]
            
            for selector in name_selectors:
                element = soup.select_one(selector)
                if element:
                    author_name = element.get_text(strip=True)
                    break
            
            # If tweet text found, return data
            if tweet_text:
                return {
                    'id': tweet_id,
                    'text': tweet_text,
                    'author_name': author_name,
                    'author_username': author_username,
                    'created_at': datetime.now().isoformat(),
                    'source': 'web_scraper'
                }
            
            return None
            
        except Exception as e:
            warning(f"[WebScraper] Error extracting tweet data: {e}")
            return None
    
    def _extract_from_json_ld(self, soup: BeautifulSoup, tweet_id: str) -> Optional[Dict]:
        """
        Extract tweet information from JSON-LD structured data
        
        Args:
            soup: BeautifulSoup object
            tweet_id: Tweet ID
            
        Returns:
            Tweet data dictionary or None
        """
        try:
            # Find JSON-LD script tags
            json_scripts = soup.find_all('script', {'type': 'application/ld+json'})
            
            for script in json_scripts:
                try:
                    data = json.loads(script.string)
                    
                    # Check if it's tweet-related structured data
                    if isinstance(data, dict) and data.get('@type') == 'SocialMediaPosting':
                        text = data.get('text', '')
                        author = data.get('author', {})
                        
                        if text:
                            return {
                                'id': tweet_id,
                                'text': text,
                                'author_name': author.get('name', ''),
                                'author_username': author.get('alternateName', '').replace('@', ''),
                                'created_at': data.get('datePublished', datetime.now().isoformat()),
                                'source': 'json_ld'
                            }
                            
                except json.JSONDecodeError:
                    continue
            
            return None
            
        except Exception as e:
            warning(f"[WebScraper] Error extracting from JSON-LD: {e}")
            return None
    
    def _extract_from_meta_tags(self, soup: BeautifulSoup, tweet_id: str) -> Optional[Dict]:
        """
        Extract tweet information from meta tags
        
        Args:
            soup: BeautifulSoup object
            tweet_id: Tweet ID
            
        Returns:
            Tweet data dictionary or None
        """
        try:
            # Extract information from meta tags
            description_meta = soup.find('meta', {'name': 'description'}) or soup.find('meta', {'property': 'og:description'})
            title_meta = soup.find('meta', {'property': 'og:title'})
            
            tweet_text = ""
            author_name = ""
            
            if description_meta:
                tweet_text = description_meta.get('content', '')
            
            if title_meta:
                title_content = title_meta.get('content', '')
                # Twitter's og:title is usually "Author Name on Twitter: Tweet Content"
                if ' on Twitter:' in title_content or ' on X:' in title_content:
                    parts = re.split(r' on (?:Twitter|X):', title_content, 1)
                    if len(parts) == 2:
                        author_name = parts[0].strip()
                        if not tweet_text:  # 如果description没有内容，使用title中的内容
                            tweet_text = parts[1].strip().strip('"')
            
            if tweet_text:
                return {
                    'id': tweet_id,
                    'text': tweet_text,
                    'author_name': author_name,
                    'author_username': '',
                    'created_at': datetime.now().isoformat(),
                    'source': 'meta_tags'
                }
            
            return None
            
        except Exception as e:
            warning(f"[WebScraper] Error extracting from meta tags: {e}")
            return None
    
    def get_media_info(self, soup: BeautifulSoup) -> Tuple[List[str], List[str]]:
        """
        Get media file URLs and types from parsed page
        
        Args:
            soup: BeautifulSoup object
            
        Returns:
            (media_urls, media_types) tuple
        """
        media_urls = []
        media_types = []
        
        try:
            # Find images
            img_selectors = [
                'img[src*="pbs.twimg.com"]',
                'img[src*="video.twimg.com"]',
                '[data-testid="tweetPhoto"] img',
                'article img[src*="pbs.twimg.com"]'
            ]
            
            for selector in img_selectors:
                images = soup.select(selector)
                for img in images:
                    src = img.get('src')
                    if src and 'pbs.twimg.com' in src:
                        # Get original size image
                        if '?format=' in src:
                            src = src.split('?')[0] + '?format=jpg&name=large'
                        elif '&name=' not in src:
                            src = src + '?name=large'
                        
                        if src not in media_urls:
                            media_urls.append(src)
                            media_types.append('photo')
            
            # Find videos
            video_selectors = [
                'video source',
                '[data-testid="videoPlayer"] video source',
                'video[src]'
            ]
            
            for selector in video_selectors:
                videos = soup.select(selector)
                for video in videos:
                    src = video.get('src')
                    if src and src not in media_urls:
                        media_urls.append(src)
                        # Determine type based on file extension
                        if src.endswith('.gif'):
                            media_types.append('animated_gif')
                        else:
                            media_types.append('video')
            
            return media_urls, media_types
                        
        except Exception as e:
            warning(f"[WebScraper] Error getting media info: {e}")
            return [], []

    def get_media_urls(self, url: str) -> List[str]:
        """
        Get media file URLs from tweet (maintain backward compatibility)
        
        Args:
            url: Twitter URL
            
        Returns:
            List of media file URLs
        """
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            media_urls, _ = self.get_media_info(soup)
            return media_urls
            
        except Exception as e:
            warning(f"[WebScraper] Error getting media URLs: {e}")
            return []
    
    def get_tweet_data(self, url: str) -> Dict:
        """
        Get complete tweet data including media information
        
        Args:
            url: Twitter URL
            
        Returns:
            Dictionary containing complete tweet information
        """
        tweet_id = self.extract_tweet_id(url)
        
        # Try multiple URL formats and methods
        strategies = [
            self._try_standard_twitter_url,
            self._try_x_com_url,
            self._try_mobile_url,
            self._try_nitter_fallback,
        ]
        
        last_exception = None
        
        for strategy in strategies:
            try:
                debug(f"[WebScraper] Trying strategy: {strategy.__name__}")
                tweet_data = strategy(tweet_id)
                if tweet_data and tweet_data.get('text'):
                    success(f"[WebScraper] Success with {strategy.__name__}")
                    return tweet_data
            except Exception as e:
                warning(f"[WebScraper] {strategy.__name__} failed: {e}")
                last_exception = e
                continue
        
        # If all strategies fail, throw the last exception
        raise Exception(f"All scraping strategies failed. Last error: {last_exception}")
    
    def _try_standard_twitter_url(self, tweet_id: str) -> Dict:
        """Try standard Twitter URL"""
        url = f"https://twitter.com/i/web/status/{tweet_id}"
        return self._fetch_and_parse(url, tweet_id)
    
    def _try_x_com_url(self, tweet_id: str) -> Dict:
        """Try X.com URL"""
        url = f"https://x.com/i/web/status/{tweet_id}"
        return self._fetch_and_parse(url, tweet_id)
    
    def _try_mobile_url(self, tweet_id: str) -> Dict:
        """Try mobile URL"""
        url = f"https://mobile.twitter.com/i/web/status/{tweet_id}"
        return self._fetch_and_parse(url, tweet_id)
    
    def _try_nitter_fallback(self, tweet_id: str) -> Dict:
        """Try using Nitter instances as fallback"""
        # Try several public Nitter instances
        nitter_instances = [
            "nitter.net",
            "nitter.it", 
            "nitter.privacydev.net"
        ]
        
        for instance in nitter_instances:
            try:
                # Nitter uses different URL format
                url = f"https://{instance}/i/status/{tweet_id}"
                return self._fetch_and_parse_nitter(url, tweet_id)
            except Exception:
                continue
                
        raise Exception("All Nitter instances failed")
    
    def _fetch_and_parse(self, url: str, tweet_id: str) -> Dict:
        """Fetch and parse standard Twitter page"""
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        
        # Check if redirected to login page
        if "login" in response.url.lower() or "authenticate" in response.url.lower():
            raise Exception("Redirected to login page")
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Try multiple extraction methods
        tweet_data = self._extract_tweet_data(soup, tweet_id)
        if not tweet_data:
            tweet_data = self._extract_from_json_ld(soup, tweet_id)
        if not tweet_data:
            tweet_data = self._extract_from_meta_tags(soup, tweet_id)
        if not tweet_data:
            tweet_data = self._extract_from_scripts(soup, tweet_id)
        
        if not tweet_data:
            raise Exception("Failed to extract tweet data from HTML")
        
        # Add media information
        media_urls, media_types = self.get_media_info(soup)
        tweet_data['media_urls'] = media_urls
        tweet_data['media_types'] = media_types
        
        # Set default values
        tweet_data['reply_to'] = None
        tweet_data['conversation_id'] = tweet_id
        
        return tweet_data
    
    def _fetch_and_parse_nitter(self, url: str, tweet_id: str) -> Dict:
        """Fetch and parse Nitter page"""
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Nitter uses different CSS selectors
        tweet_data = self._extract_from_nitter(soup, tweet_id)
        
        if not tweet_data:
            raise Exception("Failed to extract tweet data from Nitter")
            
        return tweet_data
    
    def _extract_from_scripts(self, soup: BeautifulSoup, tweet_id: str) -> Optional[Dict]:
        """
        Extract tweet information from page's JavaScript data
        
        Args:
            soup: BeautifulSoup object
            tweet_id: Tweet ID
            
        Returns:
            Tweet data dictionary or None
        """
        try:
            # Find all script tags
            scripts = soup.find_all('script')
            
            for script in scripts:
                if not script.string:
                    continue
                    
                script_content = script.string
                
                # Find patterns containing tweet data
                patterns = [
                    rf'"id_str"\s*:\s*"{tweet_id}"',
                    rf'"rest_id"\s*:\s*"{tweet_id}"',
                    rf'"{tweet_id}"'
                ]
                
                for pattern in patterns:
                    if re.search(pattern, script_content):
                        # 尝试解析JSON数据
                        try:
                            # Find possible JSON structures
                            json_matches = re.findall(r'\{[^{}]*"text"[^{}]*\}', script_content)
                            for json_str in json_matches:
                                try:
                                    data = json.loads(json_str)
                                    if 'text' in data and len(data['text']) > 10:
                                        return {
                                            'id': tweet_id,
                                            'text': data['text'],
                                            'author_name': data.get('user', {}).get('name', ''),
                                            'author_username': data.get('user', {}).get('screen_name', ''),
                                            'created_at': data.get('created_at', datetime.now().isoformat()),
                                            'source': 'scripts'
                                        }
                                except json.JSONDecodeError:
                                    continue
                        except Exception:
                            continue
            
            return None
            
        except Exception as e:
            warning(f"[WebScraper] Error extracting from scripts: {e}")
            return None
    
    def _extract_from_nitter(self, soup: BeautifulSoup, tweet_id: str) -> Optional[Dict]:
        """
        Extract tweet information from Nitter page
        
        Args:
            soup: BeautifulSoup object
            tweet_id: Tweet ID
            
        Returns:
            Tweet data dictionary or None
        """
        try:
            # Nitter's tweet content selectors
            tweet_content = soup.select_one('.tweet-content')
            if not tweet_content:
                tweet_content = soup.select_one('.tweet-text')
                
            if tweet_content:
                text = tweet_content.get_text(strip=True)
                
                # Get author information
                author_name = ""
                author_username = ""
                
                username_elem = soup.select_one('.username')
                if username_elem:
                    author_username = username_elem.get_text(strip=True).replace('@', '')
                
                fullname_elem = soup.select_one('.fullname')
                if fullname_elem:
                    author_name = fullname_elem.get_text(strip=True)
                
                if text:
                    return {
                        'id': tweet_id,
                        'text': text,
                        'author_name': author_name,
                        'author_username': author_username,
                        'created_at': datetime.now().isoformat(),
                        'media_urls': [],
                        'media_types': [],
                        'source': 'nitter'
                    }
                    
            return None
            
        except Exception as e:
            warning(f"[WebScraper] Error extracting from Nitter: {e}")
            return None

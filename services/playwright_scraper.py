#!/usr/bin/env python3
"""
Twitter Playwright web scraping service
Uses real browser automation to get tweet content, solving dynamic loading and anti-scraping issues
"""

import asyncio
import json
import re
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError
import random
from utils.realtime_logger import info, error, warning, success, debug


class TwitterPlaywrightScraper:
    """Playwright-based Twitter web scraper"""
    
    def __init__(self, headless: bool = True, timeout: int = 60, debug: bool = False):
        """
        Initialize Playwright scraper
        
        Args:
            headless: Whether to run browser in headless mode
            timeout: Page load timeout (seconds)
            debug: Whether to enable debug mode (will save screenshots, etc.)
        """
        self.headless = headless
        self.timeout = timeout * 1000  # Playwright uses milliseconds
        self.debug = debug
        self.browser = None
        self.context = None
        
        # Configuration to avoid detection
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]
        
        self.viewports = [
            {'width': 1920, 'height': 1080},
            {'width': 1366, 'height': 768},
            {'width': 1536, 'height': 864},
            {'width': 1440, 'height': 900}
        ]
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self._setup_browser()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self._cleanup_browser()
    
    async def _setup_browser(self):
        """Setup browser and context"""
        self.playwright = await async_playwright().start()
        
        # Randomly select user agent and viewport
        user_agent = random.choice(self.user_agents)
        viewport = random.choice(self.viewports)
        
        # Launch browser with enhanced anti-detection
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-features=VizDisplayCompositor',
                '--disable-blink-features=AutomationControlled',
                '--disable-automation',
                '--disable-dev-shm-usage',
                '--disable-extensions',
                '--disable-plugins',
                '--disable-default-apps',
                '--disable-translate',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-field-trial-config',
                '--disable-back-forward-cache',
                '--disable-ipc-flooding-protection',
                '--no-first-run',
                '--enable-features=NetworkService,NetworkServiceLogging',
                '--disable-features=TranslateUI',
                '--disable-component-extensions-with-background-pages',
            ]
        )
        
        # Create browser context with enhanced video support
        self.context = await self.browser.new_context(
            user_agent=user_agent,
            viewport=viewport,
            locale='en-US',  # Use English to match typical browsers
            timezone_id='America/New_York',
            # Essential headers for Twitter video playback
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
            },
            ignore_https_errors=True,
            java_script_enabled=True,
            bypass_csp=True
        )
        
        # Set additional anti-detection measures and video support
        await self.context.add_init_script("""
            // Remove webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            // Fake chrome object
            window.chrome = {
                runtime: {},
            };
            
            // Enable autoplay and media support
            Object.defineProperty(HTMLMediaElement.prototype, 'autoplay', {
                get: () => true,
                set: () => {},
            });
            
            // Override media canPlay methods to always return true
            HTMLVideoElement.prototype.canPlayType = function(type) {
                if (type.includes('mp4')) return 'probably';
                if (type.includes('webm')) return 'probably';
                if (type.includes('ogg')) return 'probably';
                return 'maybe';
            };
            
            // Set media volume to ensure it's not muted
            HTMLMediaElement.prototype.muted = false;
            HTMLMediaElement.prototype.volume = 1.0;
            
            // Fake permissions to always grant media access
            const originalQuery = window.navigator.permissions?.query;
            if (originalQuery) {
                window.navigator.permissions.query = (parameters) => {
                    if (parameters.name === 'camera' || parameters.name === 'microphone') {
                        return Promise.resolve({ state: 'granted' });
                    }
                    return originalQuery(parameters);
                };
            }
        """)
    
    async def _cleanup_browser(self):
        """Clean up browser resources"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
    
    def extract_tweet_id(self, url: str) -> str:
        """
        Extract tweet ID from URL
        
        Args:
            url: Twitter URL
            
        Returns:
            Tweet ID
        """
        patterns = [
            r'twitter\.com/\w+/status/(\d+)',
            r'x\.com/\w+/status/(\d+)',
            r'mobile\.twitter\.com/\w+/status/(\d+)',
            r'twitter\.com/i/web/status/(\d+)',
            r'x\.com/\w+/article/(\d+)',
            r'twitter\.com/\w+/article/(\d+)',
            r'status/(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        raise ValueError(f"Unable to extract tweet ID from URL: {url}")
    
    def _fix_avatar_url(self, avatar_url: str) -> str:
        """
        Fix avatar URL format to get high quality version
        
        Args:
            avatar_url: Original avatar URL
            
        Returns:
            Fixed avatar URL
        """
        try:
            # Twitter avatar URL format:
            # Original: https://pbs.twimg.com/profile_images/xxx/yyy_normal.jpg
            # High quality: https://pbs.twimg.com/profile_images/xxx/yyy_400x400.jpg
            
            if '_normal.' in avatar_url:
                # Replace _normal with _400x400 to get high quality avatar
                high_quality_url = avatar_url.replace('_normal.', '_400x400.')
                # Remove possible parameters
                if '?' in high_quality_url:
                    high_quality_url = high_quality_url.split('?')[0]
                return high_quality_url
            elif 'profile_images' in avatar_url:
                # If no _normal, try to get original URL directly
                if '?' in avatar_url:
                    avatar_url = avatar_url.split('?')[0]
                # Try to add _400x400
                parts = avatar_url.rsplit('.', 1)
                if len(parts) == 2:
                    return f"{parts[0]}_400x400.{parts[1]}"
                return avatar_url
            else:
                return avatar_url
                
        except Exception as e:
            warning(f"[PlaywrightScraper] Avatar URL fix failed: {e}")
            return avatar_url
    
    async def get_tweet_data(self, url: str) -> Dict:
        """
        Get complete tweet data including media information
        
        Args:
            url: Twitter URL
            
        Returns:
            Dictionary containing complete tweet information
        """
        # 检测是否为长文 article URL，如果是则走专门的长文抓取逻辑
        from utils.url_parser import TwitterURLParser
        if TwitterURLParser.is_article_url(url):
            info(f"[PlaywrightScraper] Detected article URL, routing to get_article_data: {url}")
            return await self.get_article_data(url)

        tweet_id = self.extract_tweet_id(url)

        # Store original URL for username extraction fallback
        self._original_url = url
        debug(f"[PlaywrightScraper] Received URL: {url}")

        # Convert to standard X.com URL，保留用户名以确保媒体正确加载
        clean_url = TwitterURLParser.normalize_url(url)
        if not clean_url:
            # 如果标准化失败，使用原始逻辑
            clean_url = f"https://x.com/i/web/status/{tweet_id}"

        info(f"[PlaywrightScraper] Getting tweet: {clean_url}")
        
        page = await self.context.new_page()
        
        # Set up network monitoring BEFORE loading the page
        captured_video_urls = []
        
        async def handle_response(response):
            try:
                url = response.url
                # Capture direct video URLs
                if 'video.twimg.com' in url and '.mp4' in url:
                    captured_video_urls.append(url)
                    debug(f"[PlaywrightScraper] Captured direct video URL: {url[:80]}...")
                elif 'pbs.twimg.com/ext_tw_video' in url:
                    captured_video_urls.append(url)
                    debug(f"[PlaywrightScraper] Captured ext video URL: {url[:80]}...")
                
                # Check ALL JSON responses for video data
                if response.status == 200:
                    try:
                        content_type = response.headers.get('content-type', '')
                        if 'json' in content_type or 'javascript' in content_type:
                            text = await response.text()
                            if 'video.twimg.com' in text or 'ext_tw_video' in text:
                                # Extract video URLs with more aggressive patterns
                                import re
                                patterns = [
                                    r'https://[^"\']*video\.twimg\.com[^"\']*\.mp4[^"\']*',
                                    r'https://[^"\']*pbs\.twimg\.com/ext_tw_video[^"\']*',
                                    r'"url":"(https://[^"]*video\.twimg\.com[^"]*\.mp4[^"]*)"',
                                    r'"videoUrl":"(https://[^"]*video\.twimg\.com[^"]*\.mp4[^"]*)"',
                                    r'"contentUrl":"(https://[^"]*video\.twimg\.com[^"]*\.mp4[^"]*)"'
                                ]
                                
                                for pattern in patterns:
                                    matches = re.findall(pattern, text)
                                    for match in matches:
                                        video_url = match if 'video.twimg.com' in match else match
                                        if video_url and video_url not in captured_video_urls:
                                            captured_video_urls.append(video_url)
                                            debug(f"[PlaywrightScraper] Captured video from JSON: {video_url[:80]}...")
                    except Exception:
                        pass
            except Exception:
                pass
        
        # Register network listener BEFORE page load
        page.on('response', handle_response)
        
        try:
            # Set additional request interception (optional)
            # await page.route("**/*.{png,jpg,jpeg,gif,svg,ico}", lambda route: route.abort())
            
            # Add random delay before visiting to mimic human behavior
            await page.wait_for_timeout(random.randint(1000, 3000))
            
            # Visit page with more reasonable wait strategy
            await page.goto(clean_url, wait_until='domcontentloaded', timeout=self.timeout)
            
            # Random mouse movement to mimic human behavior
            await page.mouse.move(random.randint(100, 500), random.randint(100, 400))
            await page.wait_for_timeout(random.randint(500, 1500))
            
            # Wait additional time for media requests to complete with timeout
            try:
                await page.wait_for_load_state('networkidle', timeout=30000)  # 30秒超时
            except Exception:
                # If networkidle timeout, proceed anyway
                debug("[PlaywrightScraper] Network idle timeout, proceeding...")
            
            # Critical: Wait longer for video content to load
            debug("[PlaywrightScraper] Waiting for video content to initialize...")
            await page.wait_for_timeout(5000)  # 等待5秒让视频加载
            
            # Try to enable video autoplay and unmute
            try:
                await page.evaluate("""
                    () => {
                        // Find and configure all video elements
                        const videos = document.querySelectorAll('video');
                        videos.forEach(video => {
                            video.muted = true;  // Mute to allow autoplay
                            video.autoplay = true;
                            video.preload = 'metadata';
                            // Try to load the video
                            if (video.load) video.load();
                        });
                    }
                """)
                await page.wait_for_timeout(3000)  # 等待视频配置生效
            except Exception as e:
                warning(f"[PlaywrightScraper] Video configuration failed: {e}")
            
            # Wait for tweet content to load with multiple strategies
            debug("[PlaywrightScraper] Waiting for Twitter page to load...")
            await self._wait_for_twitter_page(page)

            # ---- 检测是否是长文（/status/ URL 有时也是长文入口）----
            # 先等待一下，给长文专属节点时间渲染（最多等6秒）
            article_detected = False
            article_selectors_to_check = [
                '[data-testid="twitterArticleRichTextView"]',
                '[data-testid="twitterArticleReadView"]',
                '[data-testid="twitter-article-title"]',
            ]
            for art_sel in article_selectors_to_check:
                try:
                    await page.wait_for_selector(art_sel, timeout=6000)
                    article_detected = True
                    info(f"[PlaywrightScraper] Article selector appeared: {art_sel}")
                    break
                except Exception:
                    continue

            if article_detected:
                info(f"[PlaywrightScraper] Article content detected on status page, re-routing: {url}")
                await page.close()
                return await self.get_article_data(url)

            # Extract tweet data
            tweet_data = await self._extract_tweet_data(page, tweet_id)
            
            # Get media information with captured video URLs
            media_urls, media_types = await self._get_media_info(page, captured_video_urls)
            tweet_data['media_urls'] = media_urls
            tweet_data['media_types'] = media_types
            
            # If in debug mode, save screenshot
            if self.debug:
                screenshot_path = f"debug_screenshot_{tweet_id}_{int(time.time())}.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                debug(f"[PlaywrightScraper] Debug screenshot saved: {screenshot_path}")
            
            # Use safe printing method to avoid encoding issues
            text_preview = tweet_data.get('text', '')[:100].encode('ascii', 'ignore').decode('ascii')
            success(f"[PlaywrightScraper] Successfully obtained tweet data: {text_preview}...")
            return tweet_data
            
        except Exception as e:
            # Also save screenshot on error for debugging
            if self.debug:
                try:
                    error_screenshot = f"error_screenshot_{tweet_id}_{int(time.time())}.png"
                    await page.screenshot(path=error_screenshot, full_page=True)
                    debug(f"[PlaywrightScraper] Error screenshot saved: {error_screenshot}")
                except Exception as screenshot_error:
                    warning(f"[PlaywrightScraper] Could not save error screenshot: {screenshot_error}")
            
            error(f"[PlaywrightScraper] Error getting tweet data from {url}: {e}")
            
            # Close page before re-raising exception
            try:
                await page.close()
            except:
                pass
            
            raise e
            
        finally:
            # Only close page if not already closed
            try:
                await page.close()
            except:
                pass

    async def get_article_data(self, url: str) -> Dict:
        """
        专门抓取 X 长文（article）内容

        关键发现（通过浏览器 DOM 检查）：
        - /status/ 页面在 <article> 内含有完整长文内容
        - 正确的 data-testid: twitterArticleRichTextView（正文）, twitter-article-title（标题）
        - /article/ 页面反而没有可靠的 data-testid
        - 所以始终导航到 /status/ URL 来提取长文

        Args:
            url: X 长文 URL（/article/ 或 /status/ 格式均可）

        Returns:
            包含长文完整内容的字典
        """
        from utils.url_parser import TwitterURLParser
        tweet_id = self.extract_tweet_id(url)
        self._original_url = url

        # 提取用户名
        username = TwitterURLParser.extract_username(url)

        # 始终使用 /status/ URL（该页面暴露完整长文 DOM）
        if username:
            status_url = f"https://x.com/{username}/status/{tweet_id}"
        else:
            status_url = f"https://x.com/i/web/status/{tweet_id}"

        info(f"[PlaywrightScraper] Getting article via status URL: {status_url}")
        page = await self.context.new_page()

        try:
            await page.wait_for_timeout(random.randint(500, 1500))
            await page.goto(status_url, wait_until='domcontentloaded', timeout=self.timeout)
            await page.mouse.move(random.randint(100, 500), random.randint(100, 400))
            await page.wait_for_timeout(random.randint(500, 1500))

            try:
                await page.wait_for_load_state('networkidle', timeout=25000)
            except Exception:
                debug("[PlaywrightScraper] Article networkidle timeout, proceeding...")

            # 等待长文特有节点出现（优先用真实 data-testid）
            article_specific_selectors = [
                '[data-testid="twitterArticleRichTextView"]',
                '[data-testid="twitterArticleReadView"]',
                '[data-testid="twitter-article-title"]',
                'article',
            ]
            found_selector = None
            for sel in article_specific_selectors:
                try:
                    await page.wait_for_selector(sel, timeout=12000)
                    found_selector = sel
                    info(f"[PlaywrightScraper] Article selector found: {sel}")
                    break
                except Exception:
                    continue

            if not found_selector:
                warning("[PlaywrightScraper] No article-specific selector found")

            # 滚动页面确保全文懒加载完成
            await page.wait_for_timeout(2000)
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 600)")
                await page.wait_for_timeout(500)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(1000)

            # ---- 通过 JavaScript 提取文章内容（使用真实 data-testid）----
            result = await page.evaluate("""
                () => {
                    // 1. 标题
                    const titleEl = document.querySelector('[data-testid="twitter-article-title"]');
                    const title = titleEl ? titleEl.innerText.trim() : '';

                    // 2. 长文正文（最精确选择器）
                    const richView = document.querySelector('[data-testid="twitterArticleRichTextView"]');
                    if (richView && richView.innerText.trim().length > 50) {
                        return { title, html: richView.innerHTML, text: richView.innerText, source: 'twitterArticleRichTextView' };
                    }

                    // 3. 回退：整体 article 读取视图
                    const readView = document.querySelector('[data-testid="twitterArticleReadView"]');
                    if (readView && readView.innerText.trim().length > 50) {
                        return { title, html: readView.innerHTML, text: readView.innerText, source: 'twitterArticleReadView' };
                    }

                    // 4. 回退：<article> 标签
                    const articleEl = document.querySelector('article');
                    if (articleEl && articleEl.innerText.trim().length > 100) {
                        return { title, html: articleEl.innerHTML, text: articleEl.innerText, source: 'article_tag' };
                    }

                    // 5. 最终回退：main 元素
                    const mainEl = document.querySelector('main');
                    if (mainEl && mainEl.innerText.trim().length > 100) {
                        return { title, html: mainEl.innerHTML, text: mainEl.innerText, source: 'main_tag' };
                    }

                    return null;
                }
            """)

            article_html = ""
            article_text = ""
            title_text = ""

            if result:
                title_text = result.get('title', '') or ''
                article_html = result.get('html', '') or ''
                article_text = result.get('text', '') or ''
                source_used = result.get('source', 'unknown')
                info(f"[PlaywrightScraper] Article extracted via '{source_used}': "
                     f"title={len(title_text)}, text={len(article_text)} chars")

                # 在文本前加标题（如果标题不在正文里）
                if title_text and not article_text.lstrip().startswith(title_text):
                    article_text = f"{title_text}\n\n{article_text}"
                    article_html = f"<h1>{title_text}</h1>\n{article_html}"
            else:
                warning("[PlaywrightScraper] Article: JS extraction returned nothing")

            # 如果内容太少，回退到普通推文提取
            if not article_text or len(article_text.strip()) < 50:
                info("[PlaywrightScraper] Article: falling back to regular tweet DOM extraction")
                tweet_data = await self._extract_tweet_data(page, tweet_id)
                media_urls, media_types = await self._get_media_info(page, [])
                tweet_data['media_urls'] = media_urls
                tweet_data['media_types'] = media_types
                return tweet_data

            # ---- 提取作者信息 ----
            author_name = ""
            author_username = username or ""

            try:
                name_result = await page.evaluate("""
                    () => {
                        const userNameEl = document.querySelector('[data-testid="User-Name"]');
                        if (userNameEl) {
                            const spans = userNameEl.querySelectorAll('span');
                            for (const sp of spans) {
                                const t = sp.innerText.trim();
                                if (t && t !== '·' && !t.startsWith('@') && t.length > 0) {
                                    return t;
                                }
                            }
                        }
                        return '';
                    }
                """)
                if name_result:
                    author_name = name_result.strip()
            except Exception:
                pass

            if not author_username:
                url_match = (re.search(r'x\.com/([^/]+)/', url) or
                             re.search(r'twitter\.com/([^/]+)/', url))
                if url_match:
                    candidate = url_match.group(1)
                    if candidate not in ['i', 'web', 'intent', 'share', 'search', 'status', 'article']:
                        author_username = candidate

            # ---- 如果仍然没有用户名，从 DOM 提取 @username ----
            if not author_username:
                try:
                    dom_username = await page.evaluate("""
                        () => {
                            const userNameEl = document.querySelector('[data-testid="User-Name"]');
                            if (userNameEl) {
                                const spans = userNameEl.querySelectorAll('span');
                                for (const sp of spans) {
                                    const t = sp.innerText.trim();
                                    if (t && t.startsWith('@')) {
                                        return t.substring(1);
                                    }
                                }
                            }
                            // 回退：从页面 URL 提取（X 会自动重定向 /i/ 到真实用户名）
                            const currentUrl = window.location.href;
                            const match = currentUrl.match(/x\\.com\\/([^/]+)\\/status/);
                            if (match && !['i', 'web', 'intent', 'share'].includes(match[1])) {
                                return match[1];
                            }
                            return '';
                        }
                    """)
                    if dom_username:
                        author_username = dom_username.strip()
                        info(f"[PlaywrightScraper] Username extracted from DOM: @{author_username}")
                except Exception as e:
                    warning(f"[PlaywrightScraper] DOM username extraction failed: {e}")
            media_urls, media_types = await self._get_media_info(page, [])

            success(f"[PlaywrightScraper] Article fully extracted: author=@{author_username}, "
                    f"text_chars={len(article_text)}, media={len(media_urls)}")

            return {
                'id': tweet_id,
                'text': article_text.strip(),
                'html_content': article_html.strip(),
                'author_name': author_name,
                'author_username': author_username,
                'created_at': datetime.now().isoformat(),
                'reply_to': None,
                'conversation_id': tweet_id,
                'media_urls': media_urls,
                'media_types': media_types,
                'is_article': True,
                'source': 'playwright_get_article_data',
            }

        except Exception as e:
            error(f"[PlaywrightScraper] Error getting article data: {e}")
            try:
                await page.close()
            except:
                pass
            raise e
        finally:
            try:
                await page.close()
            except:
                pass

    async def _extract_tweet_data_with_media(self, page, tweet_id: str, original_url: str) -> Dict:
        """Helper: extract tweet data and append media info"""
        tweet_data = await self._extract_tweet_data(page, tweet_id)
        media_urls, media_types = await self._get_media_info(page, [])
        tweet_data['media_urls'] = media_urls
        tweet_data['media_types'] = media_types
        return tweet_data

    async def _wait_for_twitter_page(self, page: Page):
        """
        等待Twitter页面加载完成，使用多种策略
        """
        debug("[PlaywrightScraper] Using progressive loading strategy...")
        
        # 策略1: 等待基本页面框架
        basic_selectors = [
            'main[role="main"]',
            '[data-testid="primaryColumn"]',
            'div[data-testid="tweet"]',
            'article[data-testid="tweet"]',
            '[role="article"]',
            'main',
        ]
        
        page_loaded = False
        for selector in basic_selectors:
            try:
                await page.wait_for_selector(selector, timeout=8000)
                debug(f"[PlaywrightScraper] Page structure detected: {selector}")
                page_loaded = True
                break
            except Exception:
                continue
        
        if not page_loaded:
            warning("[PlaywrightScraper] Basic page structure not detected, proceeding anyway...")
        
        # 策略2: 等待内容加载
        await page.wait_for_timeout(2000)
        
        # 策略3: 等待字体和样式加载
        try:
            await page.wait_for_load_state('networkidle', timeout=10000)
        except Exception:
            debug("[PlaywrightScraper] Network idle timeout, content may still be loading...")
        
        # 策略4: 检查是否有错误页面
        await self._check_for_error_page(page)
        
        debug("[PlaywrightScraper] Page loading completed")
    
    async def _check_for_error_page(self, page: Page):
        """检查是否遇到了错误页面"""
        try:
            # 检查常见的错误指示器
            error_indicators = [
                'text="Something went wrong"',
                'text="This page doesn\'t exist"',
                'text="页面不存在"',
                '[data-testid="error"]',
                '.ErrorPage',
            ]
            
            for indicator in error_indicators:
                element = await page.query_selector(indicator)
                if element:
                    error_text = await element.inner_text() if element else "Unknown error"
                    raise Exception(f"Twitter error page detected: {error_text}")
                    
        except Exception as e:
            if "Twitter error page detected" in str(e):
                raise e
            # 其他异常忽略，继续处理
    
    async def _wait_for_tweet_content(self, page: Page, tweet_id: str):
        """
        等待推文内容加载完成
        
        Args:
            page: Playwright页面对象
            tweet_id: 推文ID
        """
        # 等待策略：尝试多种选择器直到找到推文内容
        selectors_to_wait = [
            '[data-testid="tweetText"]',
            '[data-testid="tweet"]',
            'article[data-testid="tweet"]',
            '[role="article"]',
            '.tweet-text',
        ]
        
        debug(f"[PlaywrightScraper] 等待推文内容加载...")
        
        # 尝试等待任何一个选择器出现
        for selector in selectors_to_wait:
            try:
                await page.wait_for_selector(selector, timeout=10000)  # 10秒超时
                debug(f"[PlaywrightScraper] 找到推文内容选择器: {selector}")
                break
            except TimeoutError:
                continue
        
        # 额外等待，确保内容完全加载
        await page.wait_for_timeout(2000)  # 等待2秒
        
        # 等待媒体内容加载（特别是视频）
        await self._wait_for_media_content(page)
        
        # 尝试滚动页面以触发懒加载
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        await page.wait_for_timeout(1000)
    
    async def _wait_for_media_content(self, page: Page):
        """
        等待媒体内容加载，特别是视频
        
        Args:
            page: Playwright页面对象
        """
        debug(f"[PlaywrightScraper] 等待媒体内容加载...")
        
        # 媒体选择器
        media_selectors = [
            'video',  # 视频标签
            '[data-testid="videoPlayer"]',  # Twitter视频播放器
            'video source',  # 视频源
            '.media-wrapper video',  # 媒体包装器中的视频
            '[role="img"]',  # 图片角色
            'img[src*="pbs.twimg.com"]',  # Twitter图片
            'img[src*="video.twimg.com"]',  # Twitter视频缩略图
        ]
        
        # 尝试等待任何媒体元素出现
        media_found = False
        for selector in media_selectors:
            try:
                await page.wait_for_selector(selector, timeout=5000)  # 5秒超时
                debug(f"[PlaywrightScraper] 找到媒体元素: {selector}")
                media_found = True
                break
            except TimeoutError:
                continue
        
        if media_found:
            # 如果找到媒体，额外等待确保完全加载
            await page.wait_for_timeout(3000)  # 等待3秒让媒体加载
            debug(f"[PlaywrightScraper] 媒体内容加载完成")
        else:
            debug(f"[PlaywrightScraper] 未检测到媒体元素，可能是纯文本推文")
    
    async def _extract_tweet_data(self, page: Page, tweet_id: str) -> Dict:
        """
        从页面中提取推文数据
        
        Args:
            page: Playwright页面对象
            tweet_id: 推文ID
            
        Returns:
            推文数据字典
        """
        # 尝试多种方法提取推文内容
        strategies = [
            self._extract_from_dom,
            self._extract_from_page_data,
            self._extract_from_meta_tags_playwright,
        ]
        
        for strategy in strategies:
            try:
                tweet_data = await strategy(page, tweet_id)
                if tweet_data and tweet_data.get('text'):
                    tweet_data['source'] = f'playwright_{strategy.__name__}'
                    return tweet_data
            except Exception as e:
                warning(f"[PlaywrightScraper] {strategy.__name__} 失败: {e}")
                continue
        
        raise Exception("所有提取策略都失败了")
    
    async def _extract_from_dom(self, page: Page, tweet_id: str) -> Optional[Dict]:
        """Extract tweet data from DOM"""
        try:
            # Tweet text and HTML content
            tweet_text = ""
            tweet_html = ""
            text_selectors = [
                '[data-testid="tweetText"]',
                'div[data-testid="tweetText"]',
                '[data-testid="tweetText"] span',
                'article[data-testid="tweet"] [lang]',
                '[role="article"] [lang]',
                'article [data-testid="tweetText"]',
                '.tweet-text',
                '[data-testid="tweet"] div[lang]',
                'div[dir="auto"][lang]',  # Modern Twitter uses this
                'article div[dir="auto"]',
            ]
            
            for selector in text_selectors:
                elements = await page.query_selector_all(selector)
                if elements:
                    texts = []
                    htmls = []
                    for element in elements:
                        text = await element.inner_text()
                        html = await element.inner_html()
                        if text and len(text.strip()) > 10:
                            # Append any t.co links hidden by Twitter's card preview
                            # (Twitter removes the last URL from visible text when it generates a card)
                            link_els = await element.query_selector_all('a[href*="t.co"]')
                            for link_el in link_els:
                                href = await link_el.get_attribute('href')
                                if href and href not in text:
                                    text = text.rstrip() + '\n' + href
                            texts.append(text.strip())
                            htmls.append(html.strip())

                    if texts:
                        tweet_text = '\n\n'.join(texts)
                        tweet_html = '\n\n'.join(htmls)
                        break
            
            # Author information
            author_name = ""
            author_username = ""
            
            # Try to get author name
            name_selectors = [
                '[data-testid="User-Name"] span',
                '.ProfileHeaderCard-name',
                '[data-testid="UserName"] > div > div:first-child span'
            ]
            
            for selector in name_selectors:
                element = await page.query_selector(selector)
                if element:
                    name = await element.inner_text()
                    if name and name not in ['·', '@']:
                        author_name = name.strip()
                        break
            
            # Try to get username
            username_selectors = [
                '[data-testid="User-Name"] [href*="/"]',
                '.ProfileHeaderCard-screenname',
                'a[href^="/"][role="link"]'
            ]
            
            for selector in username_selectors:
                element = await page.query_selector(selector)
                if element:
                    href = await element.get_attribute('href')
                    if href and href.startswith('/'):
                        username = href.strip('/').split('/')[0]
                        if username and not username.startswith('http'):
                            author_username = username
                            break
            
            if tweet_text:
                # If username is still empty, extract from original URL as fallback
                if not author_username and hasattr(self, '_original_url'):
                    url_match = re.search(r'x\.com/([^/]+)/', self._original_url) or re.search(r'twitter\.com/([^/]+)/', self._original_url)
                    if url_match:
                        potential_username = url_match.group(1)
                        if potential_username not in ['i', 'web', 'intent', 'share', 'search', 'status']:
                            author_username = potential_username
                            debug(f"[PlaywrightScraper] DOM: Extracted username from URL: {author_username}")

                return {
                    'id': tweet_id,
                    'text': tweet_text,
                    'html_content': tweet_html,
                    'author_name': author_name,
                    'author_username': author_username,
                    'created_at': datetime.now().isoformat(),
                    'reply_to': None,
                    'conversation_id': tweet_id
                }
            
            return None
            
        except Exception as e:
            warning(f"[PlaywrightScraper] DOM extraction failed: {e}")
            return None
    
    async def _extract_from_page_data(self, page: Page, tweet_id: str) -> Optional[Dict]:
        """Extract tweet information from page's JavaScript data"""
        try:
            # Try to get data from window object
            page_data = await page.evaluate("""
                () => {
                    // Try to get data from various possible global variables
                    const sources = [
                        window.__INITIAL_STATE__,
                        window.__DATA__,
                        window.__APOLLO_STATE__,
                        window.YTD,
                    ];
                    
                    for (const source of sources) {
                        if (source && typeof source === 'object') {
                            return JSON.stringify(source);
                        }
                    }
                    
                    return null;
                }
            """)
            
            if page_data:
                data = json.loads(page_data)
                # Recursively search for tweet data
                tweet_data = self._find_tweet_in_data(data, tweet_id)
                if tweet_data:
                    return tweet_data
            
            return None
            
        except Exception as e:
            warning(f"[PlaywrightScraper] Page data extraction failed: {e}")
            return None
    
    def _find_tweet_in_data(self, data: any, tweet_id: str) -> Optional[Dict]:
        """Recursively search for tweet information in data structure"""
        if isinstance(data, dict):
            # Check if current dictionary contains tweet data
            if data.get('id_str') == tweet_id or data.get('rest_id') == tweet_id:
                text = data.get('full_text') or data.get('text', '')
                if text:
                    user = data.get('user', {})
                    return {
                        'id': tweet_id,
                        'text': text,
                        'html_content': None,  # JSON data doesn't contain HTML
                        'author_name': user.get('name', ''),
                        'author_username': user.get('screen_name', ''),
                        'created_at': data.get('created_at', datetime.now().isoformat()),
                        'reply_to': data.get('in_reply_to_status_id_str'),
                        'conversation_id': data.get('conversation_id_str', tweet_id)
                    }
            
            # Recursively search sub-dictionaries
            for value in data.values():
                result = self._find_tweet_in_data(value, tweet_id)
                if result:
                    return result
        
        elif isinstance(data, list):
            # Recursively search list items
            for item in data:
                result = self._find_tweet_in_data(item, tweet_id)
                if result:
                    return result
        
        return None
    
    async def _extract_from_meta_tags_playwright(self, page: Page, tweet_id: str) -> Optional[Dict]:
        """Extract tweet information from meta tags"""
        try:
            debug("[PlaywrightScraper] Attempting meta tags extraction...")
            
            # Get page title (this usually works)
            title = await page.title()
            debug(f"[PlaywrightScraper] Page title: {title[:100] if title else 'None'}...")
            
            # Try to get meta tags with timeout handling
            description = None
            og_title = None
            
            try:
                description = await page.get_attribute('meta[name="description"]', 'content', timeout=5000)
            except Exception:
                try:
                    description = await page.get_attribute('meta[property="og:description"]', 'content', timeout=5000)
                except Exception:
                    debug("[PlaywrightScraper] Description meta tags not found")
            
            try:
                og_title = await page.get_attribute('meta[property="og:title"]', 'content', timeout=5000)
            except Exception:
                debug("[PlaywrightScraper] OG title meta tag not found")
            
            tweet_text = ""
            author_name = ""
            author_username = ""
            
            if description:
                tweet_text = description
                debug(f"[PlaywrightScraper] Found description: {description[:50]}...")
            
            if og_title:
                debug(f"[PlaywrightScraper] Found og:title: {og_title[:50]}...")
                # Twitter's og:title is usually "Author Name on X: Tweet Content"
                if ' on X:' in og_title or ' on Twitter:' in og_title:
                    parts = re.split(r' on (?:X|Twitter):', og_title, 1)
                    if len(parts) == 2:
                        author_name = parts[0].strip()
                        if not tweet_text:
                            tweet_text = parts[1].strip().strip('"')
                elif ' (@' in og_title and ')' in og_title:
                    # Format: "Name (@username) / X"
                    match = re.match(r'^(.+?) \(@(.+?)\)', og_title)
                    if match:
                        author_name = match.group(1).strip()
                        author_username = match.group(2).strip()
            
            # If no content from meta, try extracting from title
            if not tweet_text and title:
                # Various title patterns Twitter uses
                patterns = [
                    r'"([^"]+)"',  # Content in quotes
                    r': "([^"]+)"',  # After colon and in quotes
                    r'on X: "([^"]+)"',  # X format
                    r'on Twitter: "([^"]+)"',  # Twitter format
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, title)
                    if match:
                        tweet_text = match.group(1)
                        debug(f"[PlaywrightScraper] Extracted from title: {tweet_text[:50]}...")
                        break
            
            if tweet_text and len(tweet_text.strip()) > 5:
                # If username is still empty, extract from original URL as fallback
                debug(f"[PlaywrightScraper] Meta: author_username = '{author_username}', has _original_url = {hasattr(self, '_original_url')}")
                if not author_username and hasattr(self, '_original_url'):
                    debug(f"[PlaywrightScraper] Meta: Attempting URL extraction from {self._original_url}")
                    url_match = re.search(r'x\.com/([^/]+)/', self._original_url) or re.search(r'twitter\.com/([^/]+)/', self._original_url)
                    if url_match:
                        potential_username = url_match.group(1)
                        debug(f"[PlaywrightScraper] Meta: Found potential username: {potential_username}")
                        if potential_username not in ['i', 'web', 'intent', 'share', 'search', 'status']:
                            author_username = potential_username
                            debug(f"[PlaywrightScraper] Meta: Extracted username from URL: {author_username}")
                        else:
                            debug(f"[PlaywrightScraper] Meta: Username '{potential_username}' is invalid")
                    else:
                        debug(f"[PlaywrightScraper] Meta: No match found in URL")

                success(f"[PlaywrightScraper] Meta extraction successful: {len(tweet_text)} chars")
                return {
                    'id': tweet_id,
                    'text': tweet_text.strip(),
                    'html_content': None,  # Meta tags don't contain HTML content
                    'author_name': author_name,
                    'author_username': author_username,
                    'created_at': datetime.now().isoformat(),
                    'reply_to': None,
                    'conversation_id': tweet_id
                }
            else:
                warning("[PlaywrightScraper] No valid content found in meta tags")
            
            return None
            
        except Exception as e:
            error(f"[PlaywrightScraper] Meta tag extraction failed: {e}")
            return None
    
    async def _get_media_info(self, page: Page, captured_video_urls: List[str] = None) -> Tuple[List[str], List[str]]:
        """
        Get media file information from page
        
        Args:
            page: Playwright page object
            captured_video_urls: Video URLs captured during page load
            
        Returns:
            (media_urls, media_types) tuple
        """
        media_urls = []
        media_types = []
        
        if captured_video_urls is None:
            captured_video_urls = []
        
        try:
            # 首先获取用户头像 - 使用更通用的方法
            debug("[PlaywrightScraper] Searching for avatar...")
            
            # Try to get all profile_images URLs via JavaScript
            avatar_urls = await page.evaluate("""
                () => {
                    const avatarUrls = [];
                    const images = document.querySelectorAll('img');
                    for (const img of images) {
                        const src = img.src;
                        if (src && src.includes('profile_images')) {
                            avatarUrls.push(src);
                        }
                    }
                    return [...new Set(avatarUrls)];  // Deduplicate
                }
            """)
            
            # 处理找到的头像
            if avatar_urls:
                debug(f"[PlaywrightScraper] Found {len(avatar_urls)} avatar URLs")
                for avatar_url in avatar_urls[:1]:  # Only take first avatar
                    fixed_avatar_url = self._fix_avatar_url(avatar_url)
                    if fixed_avatar_url and fixed_avatar_url not in media_urls:
                        media_urls.append(fixed_avatar_url)
                        media_types.append('avatar')
                        debug(f"[PlaywrightScraper] Added avatar: {fixed_avatar_url[:60]}...")
                        break
            else:
                debug("[PlaywrightScraper] No avatar found")
            
            # Get media images from tweet (excluding avatars)
            media_img_selectors = [
                '[data-testid="tweetPhoto"] img',
                'article img[src*="pbs.twimg.com/media/"]',
                'img[src*="pbs.twimg.com/media/"]',
                '[role="article"] img[src*="pbs.twimg.com/media/"]'
            ]
            
            for selector in media_img_selectors:
                images = await page.query_selector_all(selector)
                for img in images:
                    src = await img.get_attribute('src')
                    if src and 'pbs.twimg.com/media/' in src:  # Only tweet media, not avatars
                        # Get original size image
                        if '?format=' in src:
                            src = src.split('?')[0] + '?format=jpg&name=large'
                        elif '&name=' not in src:
                            src = src + '?name=large'
                        
                        if src not in media_urls:
                            media_urls.append(src)
                            media_types.append('photo')
            
            # Also check for images in tweet content using different approach
            if not any(media_type == 'photo' for media_type in media_types):  # Only if no media found yet
                # Look for any images in the tweet article that might be media
                article_images = await page.query_selector_all('article img')
                for img in article_images:
                    src = await img.get_attribute('src')
                    if src and ('pbs.twimg.com/media/' in src or 'video.twimg.com' in src):
                        if src not in media_urls and 'profile_images' not in src:
                            # Clean and optimize URL
                            if 'pbs.twimg.com/media/' in src:
                                if '?format=' in src:
                                    src = src.split('?')[0] + '?format=jpg&name=large'
                                elif '&name=' not in src:
                                    src = src + '?name=large'
                                media_urls.append(src)
                                media_types.append('photo')
                            elif 'video.twimg.com' in src:
                                media_urls.append(src)
                                media_types.append('video')
            
            # Wait a bit for network requests to complete and capture video URLs
            await page.wait_for_timeout(3000)
            
            # Enhanced video player interaction to trigger video loading
            video_players = await page.query_selector_all('[data-testid="videoPlayer"]')
            if video_players:
                info(f"[PlaywrightScraper] Found {len(video_players)} video players, attempting deep interaction...")
                try:
                    player = video_players[0]
                    
                    # Scroll to video and ensure it's visible
                    await player.scroll_into_view_if_needed()
                    await page.wait_for_timeout(1000)
                    
                    # Hover to trigger preview loading
                    await player.hover()
                    await page.wait_for_timeout(2000)
                    
                    # Try multiple interaction methods
                    async def click_player():
                        await player.click()
                    
                    async def dblclick_player():
                        await player.dblclick()
                    
                    async def mouse_click_player():
                        bbox = await player.bounding_box()
                        if bbox:
                            await page.mouse.click(bbox['x'] + bbox['width']/2, bbox['y'] + bbox['height']/2)
                    
                    async def press_space():
                        await page.keyboard.press('Space')
                    
                    interaction_methods = [
                        click_player,
                        dblclick_player,
                        mouse_click_player,
                        press_space,
                    ]
                    
                    for i, method in enumerate(interaction_methods):
                        try:
                            debug(f"[PlaywrightScraper] Trying interaction method {i+1}...")
                            await method()
                            await page.wait_for_timeout(3000)  # Wait longer for video to load
                            
                            # Check if video sources appeared
                            video_elements = await page.query_selector_all('video')
                            for video in video_elements:
                                src = await video.get_attribute('src')
                                if src and 'video.twimg.com' in src and src not in media_urls:
                                    media_urls.append(src)
                                    media_types.append('video')
                                    debug(f"[PlaywrightScraper] Found video via interaction: {src[:60]}...")
                                    break
                            
                            # Also check video source elements
                            sources = await page.query_selector_all('video source')
                            for source in sources:
                                src = await source.get_attribute('src')
                                if src and 'video.twimg.com' in src and src not in media_urls:
                                    media_urls.append(src)
                                    media_types.append('video')
                                    debug(f"[PlaywrightScraper] Found video source via interaction: {src[:60]}...")
                                    break
                                    
                            # Break if we found a video
                            if any(typ == 'video' for typ in media_types):
                                break
                                
                        except Exception as e:
                            warning(f"[PlaywrightScraper] Interaction method {i+1} failed: {e}")
                            continue
                            
                except Exception as e:
                    warning(f"[PlaywrightScraper] Video player interaction failed: {e}")
            
            # Process videos from captured URLs (network monitoring)
            # WARNING: Network monitoring may capture videos from OTHER tweets on the page
            # We need to verify videos belong to the current tweet by checking if they're in the DOM
            if captured_video_urls:
                info(f"[PlaywrightScraper] Processing {len(captured_video_urls)} captured video URLs")

                # Get all video URLs that are actually visible in the MAIN ARTICLE
                visible_video_urls = await page.evaluate(r"""
                    () => {
                        const videoUrls = [];
                        // Only check the first article (main tweet)
                        const mainArticle = document.querySelector('article');
                        if (mainArticle) {
                            const videos = mainArticle.querySelectorAll('video');
                            for (const video of videos) {
                                if (video.src && video.src.includes('video.twimg.com')) {
                                    videoUrls.push(video.src);
                                }
                                const sources = video.querySelectorAll('source');
                                for (const source of sources) {
                                    if (source.src && source.src.includes('video.twimg.com')) {
                                        videoUrls.push(source.src);
                                    }
                                }
                            }
                        }
                        return videoUrls;
                    }
                """)

                # Only keep captured videos that are also visible in the main article
                mp4_urls = [url for url in captured_video_urls
                           if '.mp4' in url and 'video.twimg.com' in url]

                if mp4_urls and visible_video_urls:
                    # Match captured video URLs with visible ones
                    # Compare base video IDs (the numeric part in the URL)
                    def get_video_id(url):
                        import re
                        match = re.search(r'/(?:amplify_video|tweet_video|ext_tw_video)/(\d+)/', url)
                        return match.group(1) if match else None

                    visible_video_ids = {get_video_id(url) for url in visible_video_urls if get_video_id(url)}

                    # Filter captured URLs to only include those matching visible video IDs
                    verified_urls = [url for url in mp4_urls
                                    if get_video_id(url) in visible_video_ids]

                    if verified_urls:
                        # Sort by resolution (prefer highest quality)
                        def get_resolution_score(url):
                            import re
                            match = re.search(r'(\d+)x(\d+)', url)
                            if match:
                                width, height = int(match.group(1)), int(match.group(2))
                                return width * height
                            return 0

                        # Filter out ad videos by finding outliers in video IDs
                        # Strategy: Group videos by ID proximity, keep the largest cluster
                        # Real videos have IDs within ~1 billion of each other
                        # Ad videos differ by 500+ trillion from real videos
                        def filter_ad_videos_from_list(video_ids):
                            if len(video_ids) <= 1:
                                return video_ids

                            try:
                                # Convert to integers
                                ids = [(vid_str, int(vid_str)) for vid_str in video_ids]

                                # Build adjacency: videos within 10 billion are related
                                threshold = 10_000_000_000  # 10 billion
                                from collections import defaultdict
                                neighbors = defaultdict(set)

                                for i, (vid_str_i, vid_i) in enumerate(ids):
                                    for j, (vid_str_j, vid_j) in enumerate(ids):
                                        if i != j and abs(vid_i - vid_j) < threshold:
                                            neighbors[vid_str_i].add(vid_str_j)

                                # Find largest connected component (cluster)
                                visited = set()
                                clusters = []

                                def dfs(vid_str, cluster):
                                    if vid_str in visited:
                                        return
                                    visited.add(vid_str)
                                    cluster.add(vid_str)
                                    for neighbor in neighbors.get(vid_str, []):
                                        dfs(neighbor, cluster)

                                for vid_str, _ in ids:
                                    if vid_str not in visited:
                                        cluster = set()
                                        dfs(vid_str, cluster)
                                        clusters.append(cluster)

                                # Return largest cluster
                                if clusters:
                                    largest = max(clusters, key=len)
                                    filtered_out = [vid for vid, _ in ids if vid not in largest]
                                    if filtered_out:
                                        debug(f"[PlaywrightScraper] Filtered out {len(filtered_out)} ad video(s): {filtered_out}")
                                    return list(largest)
                                return video_ids
                            except Exception as e:
                                debug(f"[PlaywrightScraper] Error filtering ads: {e}, keeping all videos")
                                return video_ids

                        # Group videos by video ID, get highest quality for each unique video
                        from collections import defaultdict

                        # First, extract all unique video IDs
                        all_video_ids = []
                        for url in verified_urls:
                            vid_id = get_video_id(url)
                            if vid_id and vid_id not in all_video_ids:
                                all_video_ids.append(vid_id)

                        # Filter out ad videos
                        valid_video_ids = set(filter_ad_videos_from_list(all_video_ids))

                        # Now group URLs by filtered video IDs
                        videos_by_id = defaultdict(list)
                        for url in verified_urls:
                            vid_id = get_video_id(url)
                            if vid_id and vid_id in valid_video_ids:
                                videos_by_id[vid_id].append(url)

                        # For each unique video, add the highest quality version
                        for vid_id, urls in videos_by_id.items():
                            best_video = max(urls, key=get_resolution_score)
                            if best_video not in media_urls:
                                media_urls.append(best_video)
                                media_types.append('video')
                                debug(f"[PlaywrightScraper] Added verified video (ID {vid_id}): {best_video[:60]}...")
                    else:
                        debug(f"[PlaywrightScraper] No captured videos matched the main tweet")
                elif mp4_urls:
                    # No visible videos in DOM yet, but check if there's a video player
                    # If video player exists, it means the tweet has video, use captured URLs
                    has_video_player = await page.evaluate(r"""
                        () => {
                            const mainArticle = document.querySelector('article');
                            if (mainArticle) {
                                const player = mainArticle.querySelector('[data-testid="videoPlayer"]');
                                return !!player;
                            }
                            return false;
                        }
                    """)

                    if has_video_player:
                        debug(f"[PlaywrightScraper] Video player found, using captured video")
                        # Sort by resolution and get best quality
                        def get_resolution_score(url):
                            import re
                            match = re.search(r'(\d+)x(\d+)', url)
                            if match:
                                width, height = int(match.group(1)), int(match.group(2))
                                return width * height
                            return 0

                        def get_video_id(url):
                            import re
                            match = re.search(r'/(?:amplify_video|tweet_video|ext_tw_video)/(\d+)/', url)
                            return match.group(1) if match else None

                        # Use the same ad filtering function as above
                        def filter_ad_videos_from_list(video_ids):
                            if len(video_ids) <= 1:
                                return video_ids

                            try:
                                ids = [(vid_str, int(vid_str)) for vid_str in video_ids]
                                threshold = 10_000_000_000  # 10 billion
                                from collections import defaultdict
                                neighbors = defaultdict(set)

                                for i, (vid_str_i, vid_i) in enumerate(ids):
                                    for j, (vid_str_j, vid_j) in enumerate(ids):
                                        if i != j and abs(vid_i - vid_j) < threshold:
                                            neighbors[vid_str_i].add(vid_str_j)

                                visited = set()
                                clusters = []

                                def dfs(vid_str, cluster):
                                    if vid_str in visited:
                                        return
                                    visited.add(vid_str)
                                    cluster.add(vid_str)
                                    for neighbor in neighbors.get(vid_str, []):
                                        dfs(neighbor, cluster)

                                for vid_str, _ in ids:
                                    if vid_str not in visited:
                                        cluster = set()
                                        dfs(vid_str, cluster)
                                        clusters.append(cluster)

                                if clusters:
                                    largest = max(clusters, key=len)
                                    filtered_out = [vid for vid, _ in ids if vid not in largest]
                                    if filtered_out:
                                        debug(f"[PlaywrightScraper] Filtered out {len(filtered_out)} ad video(s): {filtered_out}")
                                    return list(largest)
                                return video_ids
                            except Exception as e:
                                debug(f"[PlaywrightScraper] Error filtering ads: {e}, keeping all videos")
                                return video_ids

                        # Extract all unique video IDs
                        all_video_ids = []
                        for url in mp4_urls:
                            vid_id = get_video_id(url)
                            if vid_id and vid_id not in all_video_ids:
                                all_video_ids.append(vid_id)

                        # Filter out ad videos
                        valid_video_ids = set(filter_ad_videos_from_list(all_video_ids))

                        # Group videos by video ID, get highest quality for each unique video
                        from collections import defaultdict
                        videos_by_id = defaultdict(list)
                        for url in mp4_urls:
                            vid_id = get_video_id(url)
                            if vid_id and vid_id in valid_video_ids:
                                videos_by_id[vid_id].append(url)
                            elif not vid_id:
                                # No video ID, add directly (fallback)
                                videos_by_id[url].append(url)

                        # For each unique video, add the highest quality version
                        for vid_id, urls in videos_by_id.items():
                            best_video = max(urls, key=get_resolution_score)
                            if best_video not in media_urls:
                                media_urls.append(best_video)
                                media_types.append('video')
                                debug(f"[PlaywrightScraper] Added video from capture (player verified, ID {vid_id}): {best_video[:60]}...")
                    else:
                        debug(f"[PlaywrightScraper] No video player in main tweet, skipping {len(mp4_urls)} captured videos")
            
            # Enhanced video detection - search page source directly
            # WARNING: Page source may contain videos from OTHER tweets
            # We'll verify against visible DOM before adding
            if not any(media_type == 'video' for media_type in media_types):
                debug("[PlaywrightScraper] No video found from network monitoring, searching page source...")

                # First, get videos that are actually visible in the main tweet
                visible_video_urls = await page.evaluate(r"""
                    () => {
                        const videoUrls = [];
                        const mainArticle = document.querySelector('article');
                        if (mainArticle) {
                            const videos = mainArticle.querySelectorAll('video');
                            for (const video of videos) {
                                if (video.src && video.src.includes('video.twimg.com')) {
                                    videoUrls.push(video.src);
                                }
                                const sources = video.querySelectorAll('source');
                                for (const source of sources) {
                                    if (source.src && source.src.includes('video.twimg.com')) {
                                        videoUrls.push(source.src);
                                    }
                                }
                            }
                        }
                        return videoUrls;
                    }
                """)

                if visible_video_urls:
                    # We found videos in the DOM, add them directly
                    for video_url in visible_video_urls:
                        if video_url not in media_urls:
                            media_urls.append(video_url)
                            media_types.append('video')
                            debug(f"[PlaywrightScraper] Added video from DOM: {video_url[:60]}...")
                else:
                    debug("[PlaywrightScraper] No video elements found in main tweet DOM")
            
            # Last resort: Use JavaScript to extract video URLs directly from DOM
            if not any(media_type == 'video' for media_type in media_types):
                debug("[PlaywrightScraper] Attempting JavaScript extraction of video URLs...")
                
                try:
                    js_video_urls = await page.evaluate(r"""
                        () => {
                            const videoUrls = [];

                            // Find the FIRST article element (the main tweet)
                            const mainArticle = document.querySelector('article');
                            if (!mainArticle) {
                                return [];
                            }

                            // Method 1: Check video elements ONLY within the main tweet article
                            const videos = mainArticle.querySelectorAll('video');
                            for (const video of videos) {
                                if (video.src && video.src.includes('video.twimg.com')) {
                                    videoUrls.push(video.src);
                                }
                                // Check source elements
                                const sources = video.querySelectorAll('source');
                                for (const source of sources) {
                                    if (source.src && source.src.includes('video.twimg.com')) {
                                        videoUrls.push(source.src);
                                    }
                                }
                            }

                            // Remove duplicates
                            return [...new Set(videoUrls)];
                        }
                    """)
                    
                    if js_video_urls:
                        debug(f"[PlaywrightScraper] JavaScript found {len(js_video_urls)} video URLs")
                        for video_url in js_video_urls:
                            if video_url not in media_urls:
                                media_urls.append(video_url)
                                media_types.append('video')
                                debug(f"[PlaywrightScraper] Added video via JavaScript: {video_url[:60]}...")
                    else:
                        debug("[PlaywrightScraper] JavaScript extraction found no video URLs")
                        
                except Exception as e:
                    warning(f"[PlaywrightScraper] JavaScript extraction failed: {e}")
            
            # Get traditional video sources (fallback)
            video_selectors = [
                'video source',
                '[data-testid="videoPlayer"] video source',
                'video[src]'
            ]
            
            for selector in video_selectors:
                videos = await page.query_selector_all(selector)
                for video in videos:
                    src = await video.get_attribute('src')
                    if src and src not in media_urls:
                        media_urls.append(src)
                        if src.endswith('.gif'):
                            media_types.append('animated_gif')
                        else:
                            media_types.append('video')
            
            # Try to get high quality media URLs from CURRENT TWEET only (not from entire page)
            # This prevents extracting videos from recommended tweets, replies, or sidebar
            high_quality_media = await page.evaluate(r"""
                () => {
                    const mediaUrls = [];

                    // Find the FIRST article element (the main tweet)
                    const mainArticle = document.querySelector('article');
                    if (!mainArticle) {
                        return [];
                    }

                    // Only search within the main tweet article
                    // Look for video elements within this article
                    const videos = mainArticle.querySelectorAll('video');
                    for (const video of videos) {
                        if (video.src && video.src.includes('video.twimg.com')) {
                            mediaUrls.push(video.src);
                        }
                        // Check source elements
                        const sources = video.querySelectorAll('source');
                        for (const source of sources) {
                            if (source.src && source.src.includes('video.twimg.com')) {
                                mediaUrls.push(source.src);
                            }
                        }
                    }

                    // Find high quality image URLs from pbs.twimg.com WITHIN the article
                    const images = mainArticle.querySelectorAll('img[src*="pbs.twimg.com/media/"]');
                    for (const img of images) {
                        if (img.src) {
                            mediaUrls.push(img.src);
                        }
                    }

                    return [...new Set(mediaUrls)];  // Deduplicate
                }
            """)
            
            # Add high quality media URLs (existing logic)
            # Deduplicate based on media ID, not full URL (to avoid downloading same image in different sizes)
            def get_media_id(url):
                """Extract media ID from Twitter media URL"""
                import re
                # Match pattern like: pbs.twimg.com/media/G2GPRz8bwAE_fWe
                match = re.search(r'/media/([^?/]+)', url)
                return match.group(1) if match else url

            existing_media_ids = {get_media_id(url) for url in media_urls}

            for url in high_quality_media:
                media_id = get_media_id(url)
                if media_id not in existing_media_ids:
                    # Standardize to large format for images
                    if 'pbs.twimg.com/media/' in url:
                        if '?format=' in url:
                            url = url.split('?')[0] + '?format=jpg&name=large'
                        elif '&name=' not in url:
                            url = url + '?name=large'

                    media_urls.append(url)
                    existing_media_ids.add(media_id)

                    if 'video.twimg.com' in url:
                        media_types.append('video')
                    else:
                        media_types.append('photo')
            
            info(f"[PlaywrightScraper] Found {len(media_urls)} media files")
            return media_urls, media_types
            
        except Exception as e:
            error(f"[PlaywrightScraper] Error getting media info: {e}")
            return [], []
        finally:
            # Remove the response listener
            try:
                page.remove_listener('response', handle_response)
            except:
                pass


# Synchronous wrapper for compatibility with existing code
class TwitterPlaywrightScraperSync:
    """Synchronous version of Playwright scraper for compatibility with existing code"""
    
    def __init__(self, headless: bool = True, timeout: int = 60, debug: bool = False):
        self.headless = headless
        self.timeout = timeout
        self.debug = debug
    
    def extract_tweet_id(self, url: str) -> str:
        """Extract tweet ID from URL"""
        scraper = TwitterPlaywrightScraper(self.headless, self.timeout, self.debug)
        return scraper.extract_tweet_id(url)
    
    def get_tweet_data(self, url: str) -> Dict:
        """Get complete tweet data including media information"""
        return asyncio.run(self._async_get_tweet_data(url))
    
    async def _async_get_tweet_data(self, url: str) -> Dict:
        """Internal method for asynchronously getting tweet data"""
        async with TwitterPlaywrightScraper(self.headless, self.timeout, self.debug) as scraper:
            return await scraper.get_tweet_data(url)
    
    def get_tweet_content(self, url: str) -> Dict:
        """Get tweet content (compatible with existing interface)"""
        return self.get_tweet_data(url)
    
    def get_media_urls(self, url: str) -> List[str]:
        """Get media URL list (compatible with existing interface)"""
        tweet_data = self.get_tweet_data(url)
        return tweet_data.get('media_urls', [])
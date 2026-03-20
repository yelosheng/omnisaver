import os
import json
import re
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path
from models.tweet import Tweet
from models.media_file import MediaFile
from utils.html_to_markdown import convert_html_to_markdown, extract_readable_content


class FileManagerError(Exception):
    """File management error"""
    pass


class FileManager:
    """File manager responsible for creating directory structure and saving content"""
    
    def __init__(self, base_path: str = "/mnt/nas/saved_tweets", create_date_folders: bool = True):
        """
        Initialize file manager
        
        Args:
            base_path: Base save path
            create_date_folders: Whether to create date folders
        """
        self.base_path = Path(base_path)
        self.create_date_folders = create_date_folders
        
        # Ensure base directory exists
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def create_save_directory(self, tweet_id: str, tweet_date: datetime = None) -> str:
        """
        Create save directory with year/month hierarchical structure
        Structure: base_path/YYYY/MM/YYYY-MM-DD_tweet_id/

        Args:
            tweet_id: Tweet ID
            tweet_date: Tweet date, if None uses current date

        Returns:
            Created directory path

        Raises:
            FileManagerError: Directory creation failed
        """
        try:
            if tweet_date is None:
                tweet_date = datetime.now()

            if self.create_date_folders:
                # Hierarchical structure: YYYY/MM/YYYY-MM-DD_tweet_id
                year = tweet_date.strftime("%Y")
                month = tweet_date.strftime("%m")
                date_str = tweet_date.strftime("%Y-%m-%d")
                dir_name = f"{date_str}_{tweet_id}"
                save_dir = self.base_path / year / month / dir_name
            else:
                # Flat structure: tweet_id only
                save_dir = self.base_path / tweet_id

            save_dir.mkdir(parents=True, exist_ok=True)
            return str(save_dir)

        except OSError as e:
            raise FileManagerError(f"Failed to create directory for tweet {tweet_id}: {e}")
    
    def get_content_file_path(self, save_dir: str) -> str:
        """
        Get content file path
        
        Args:
            save_dir: Save directory
            
        Returns:
            Content file path
        """
        return os.path.join(save_dir, "content.txt")
    
    def get_metadata_file_path(self, save_dir: str) -> str:
        """
        Get metadata file path
        
        Args:
            save_dir: Save directory
            
        Returns:
            Metadata file path
        """
        return os.path.join(save_dir, "metadata.json")
    
    def save_tweet_content(self, tweet: Tweet, save_dir: str, media_files: List[MediaFile] = None) -> None:
        """
        Save single tweet content
        
        Args:
            tweet: Tweet object
            save_dir: Save directory
            media_files: Media file list
            
        Raises:
            FileManagerError: Save failed
        """
        try:
            # Save pure tweet text to content.txt
            content_file = self.get_content_file_path(save_dir)
            with open(content_file, 'w', encoding='utf-8') as f:
                f.write(tweet.text)
            
            # Save Reader-mode HTML if HTML content is available
            if tweet.html_content:
                html_file = os.path.join(save_dir, "content.html")
                with open(html_file, 'w', encoding='utf-8') as f:

                    is_article_html = any(marker in tweet.html_content for marker in [
                        'twitterArticleRichTextView',
                        'twitterArticleReadView',
                        'twitter-article-title',
                        'longformRichTextComponent',
                    ])

                    if is_article_html:
                        # 长文：使用标签白名单剥离无用的由 CSS 控制的布局标签，从而智能提纯原生 HTML 的排版（包含标题、引语、加粗）
                        from bs4 import BeautifulSoup
                        
                        soup = BeautifulSoup(tweet.html_content, 'html.parser')
                        
                        # 解除包裹图片的 <a> 链接，避免点击图片时跳转到外部链接
                        for a in soup.find_all('a'):
                            if a.find('img') and not a.get_text(strip=True):
                                a.unwrap()

                        # 清理 Emoji 图片为其原始字符
                        for img in soup.find_all('img'):
                            if 'emoji' in img.get('src', '') or 'emoji' in img.get('alt', '').lower():
                                alt = img.get('alt', '')
                                if alt:
                                    img.replace_with(alt)
                                else:
                                    img.decompose()
                                    
                        # 将 Twitter 特有的加粗样式转换为 <strong>
                        for span in soup.find_all('span', class_=lambda c: c and 'r-b88u0q' in c):
                            span.name = 'strong'
                            
                        # 允许保留的白名单排版标签
                        whitelist_tags = {
                            'p', 'br', 'img', 'a', 
                            'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 
                            'strong', 'b', 'em', 'i', 
                            'blockquote', 'ul', 'ol', 'li'
                        }
                        
                        block_elements_to_check = list(whitelist_tags.union({'div', 'section', 'article', 'main'}) - {'a', 'img', 'strong', 'b', 'em', 'i', 'br'})
                        
                        # 转换单纯包裹文本内容的 div 为 p，强制保持段落之间的距离
                        for div in soup.find_all('div'):
                            if not div.find(block_elements_to_check):
                                div.name = 'p'
                                
                        # 遍历 DOM（需要 list 化防止原地解包引起的无限循环），清理并提纯
                        for tag in list(soup.find_all(True)):
                            if tag.name not in whitelist_tags:
                                tag.unwrap()
                            else:
                                attrs = dict(tag.attrs)
                                tag.attrs.clear()
                                if tag.name == 'img' and 'src' in attrs:
                                    tag['src'] = attrs['src']
                                elif tag.name == 'a' and 'href' in attrs:
                                    tag['href'] = attrs['href']
                                    tag['target'] = '_blank'
                                    
                        clean_html = str(soup)
                        # 清理过度重复的空行以及无意义的空段落
                        clean_html = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', clean_html)
                        clean_html = re.sub(r'<p>\s*</p>', '', clean_html)

                        article_html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>长文</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            max-width: 720px;
            margin: 0 auto;
            padding: 40px 20px;
            line-height: 1.8;
            background-color: #fefefe;
            color: #2c3e50;
            font-size: 17px;
        }}
        .reader-content img {{
            max-width: 100%;
            border-radius: 8px;
            margin: 12px auto;
            display: block;
        }}
        .reader-content p, .reader-content div {{
            margin-bottom: 12px;
        }}
        .reader-content h1 {{ font-size: 1.7em; margin: 1.2em 0 0.6em; }}
        .reader-content h2 {{ font-size: 1.4em; margin: 1em 0 0.5em; }}
        .reader-content h3 {{ font-size: 1.15em; margin: 0.8em 0 0.4em; }}
        .reader-content blockquote {{
            border-left: 4px solid #e1e8ed;
            margin: 1.5em 0;
            padding: 0.5em 1em;
            background: #f7f9fa;
            color: #536471;
            font-style: italic;
        }}
        .reader-content a {{ color: #1da1f2; text-decoration: none; }}
        span, div {{ max-width: 100%; word-wrap: break-word; }}
    </style>
</head>
<body>
<article>
    <div class="reader-content">
        {raw_html}
    </div>
</article>
</body>
</html>"""
                        f.write(article_html_template.format(raw_html=clean_html))

                    else:
                        # 普通推文：保留原始换行，不做智能合并

                        reader_content = extract_readable_content(tweet.html_content, preserve_linebreaks=True)

                        html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reader模式</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            max-width: 650px;
            margin: 0 auto;
            padding: 40px 20px;
            line-height: 1.8;
            background-color: #fefefe;
            color: #2c3e50;
        }}
        .reader-content {{
            font-size: 18px;
            line-height: 1.8;
            color: #2c3e50;
        }}
        .reader-content p {{ margin-bottom: 16px; }}
        .reader-content strong {{ font-weight: 600; color: #1a202c; }}
        .reader-content a {{
            color: #3182ce;
            text-decoration: none;
            border-bottom: 1px solid rgba(49, 130, 206, 0.3);
        }}
        .reader-content a:hover {{ border-bottom-color: #3182ce; }}
        .mention {{ color: #1da1f2; font-weight: 500; }}
        .hashtag {{ color: #1da1f2; font-weight: 500; }}
        @media print {{ body {{ max-width: none; padding: 20px; }} }}
    </style>
</head>
<body>
<article>
    <div class="reader-content">
        {reader_content}
    </div>
</article>
</body>
</html>"""

                        formatted_content = reader_content
                        formatted_content = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', formatted_content)
                        formatted_content = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', formatted_content)

                        paragraphs = formatted_content.split('\n\n')
                        formatted_paragraphs = []
                        for paragraph in paragraphs:
                            paragraph = paragraph.strip()
                            if paragraph:
                                paragraph = paragraph.replace('\n', '<br>')
                                formatted_paragraphs.append(f'<p>{paragraph}</p>')
                        formatted_content = '\n'.join(formatted_paragraphs)

                        formatted_content = re.sub(
                            r'\[LINK:([^|]+)\|([^\]]+)\]',
                            r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
                            formatted_content
                        )
                        formatted_content = re.sub(r'@(\w+)', r'<span class="mention">@\1</span>', formatted_content)
                        formatted_content = re.sub(r'#(\w+)', r'<span class="hashtag">#\1</span>', formatted_content)

                        f.write(html_template.format(reader_content=formatted_content))
            
        except IOError as e:
            raise FileManagerError(f"Failed to save tweet content: {e}")
    
    def save_thread_content(self, tweets: List[Tweet], save_dir: str, media_files: List[MediaFile] = None,
                            tweet_media_map: List[List[MediaFile]] = None) -> None:
        """
        Save thread content

        Args:
            tweets: Tweet list (sorted by time)
            save_dir: Save directory
            media_files: Flat list of all media files
            tweet_media_map: Per-tweet media files (list[i] = media files for tweets[i])

        Raises:
            FileManagerError: Save failed
        """
        if not tweets:
            raise FileManagerError("No tweets to save")

        try:
            # Save pure thread text to content.txt
            content_file = self.get_content_file_path(save_dir)
            with open(content_file, 'w', encoding='utf-8') as f:
                for i, tweet in enumerate(tweets, 1):
                    if i > 1:
                        f.write("\n\n")
                    f.write(tweet.text)

            # Always generate content.html — use html_content if available, otherwise plain text
            first_tweet = tweets[0]
            html_file = os.path.join(save_dir, "content.html")
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Thread — {first_tweet.author_name or ''} (@{first_tweet.author_username or ''})</title>
</head>
<body>
""")
                for i, tweet in enumerate(tweets):
                    if tweet.html_content:
                        body = convert_html_to_markdown(tweet.html_content)
                    else:
                        import html as _html
                        body = _html.escape(tweet.text).replace('\n', '<br>')

                    # Per-tweet media: use relative paths (view route will rewrite to /media/<id>/...)
                    media_html = ''
                    per_tweet_files = (tweet_media_map[i] if tweet_media_map and i < len(tweet_media_map) else [])
                    for mf in per_tweet_files:
                        rel = os.path.relpath(mf.local_path, save_dir).replace('\\', '/')
                        if mf.media_type in ('photo', 'image'):
                            media_html += f'<img src="{rel}" style="max-width:100%;border-radius:8px;margin:8px 0;display:block;">\n'
                        elif mf.media_type in ('video', 'animated_gif'):
                            media_html += (f'<video controls style="max-width:100%;border-radius:8px;margin:8px 0;">'
                                           f'<source src="{rel}" type="video/mp4"></video>\n')

                    f.write(f'<div class="thread-tweet" style="margin-bottom:20px;padding-bottom:20px;'
                            f'border-bottom:1px solid #e1e8ed;">\n'
                            f'<p style="white-space:pre-line;margin:0 0 8px;">{body}</p>\n'
                            f'{media_html}</div>\n')

                f.write("</body>\n</html>")

        except IOError as e:
            raise FileManagerError(f"Failed to save thread content: {e}")
    
    def save_metadata(self, tweets: List[Tweet], save_dir: str, media_files: List[MediaFile] = None) -> None:
        """
        Save metadata to JSON file
        
        Args:
            tweets: Tweet list
            save_dir: Save directory
            media_files: Media file list
            
        Raises:
            FileManagerError: Save failed
        """
        try:
            metadata_file = self.get_metadata_file_path(save_dir)
            
            # Build metadata
            metadata = {
                "saved_at": datetime.now().isoformat(),
                "tweet_count": len(tweets),
                "is_thread": len(tweets) > 1,
                "tweets": [],
                "media_files": []
            }
            
            # Add tweet data
            for tweet in tweets:
                tweet_data = {
                    "id": tweet.id,
                    "text": tweet.text,
                    "html_content": tweet.html_content,
                    "author_username": tweet.author_username,
                    "author_name": tweet.author_name,
                    "created_at": tweet.created_at.isoformat(),
                    "conversation_id": tweet.conversation_id,
                    "reply_to": tweet.reply_to,
                    "media_count": len(tweet.media_urls),
                    "media_urls": tweet.media_urls,
                    "media_types": tweet.media_types
                }
                metadata["tweets"].append(tweet_data)
            
            # Add media file data
            if media_files:
                for media_file in media_files:
                    media_data = {
                        "filename": media_file.filename,
                        "local_path": media_file.local_path,
                        "media_type": media_file.media_type,
                        "original_url": media_file.url
                    }
                    metadata["media_files"].append(media_data)
            
            # Save to file
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
                
        except (IOError, json.JSONEncodeError) as e:
            raise FileManagerError(f"Failed to save metadata: {e}")
    
    def get_save_summary(self, save_dir: str, tweets: List[Tweet], media_files: List[MediaFile] = None) -> Dict[str, Any]:
        """
        Generate save summary information
        
        Args:
            save_dir: Save directory
            tweets: Tweet list
            media_files: Media file list
            
        Returns:
            Save summary dictionary
        """
        summary = {
            "save_directory": save_dir,
            "tweet_count": len(tweets),
            "is_thread": len(tweets) > 1,
            "media_count": len(media_files) if media_files else 0,
            "files_created": []
        }
        
        # 检查创建的文件
        content_file = self.get_content_file_path(save_dir)
        metadata_file = self.get_metadata_file_path(save_dir)
        
        if os.path.exists(content_file):
            summary["files_created"].append("content.txt")
        
        if os.path.exists(metadata_file):
            summary["files_created"].append("metadata.json")
        
        # 添加媒体文件信息
        if media_files:
            image_count = sum(1 for mf in media_files if mf.media_type == 'photo')
            video_count = sum(1 for mf in media_files if mf.media_type in ['video', 'animated_gif'])
            
            summary["image_count"] = image_count
            summary["video_count"] = video_count
            
            if image_count > 0:
                summary["files_created"].append(f"images/ ({image_count} files)")
            if video_count > 0:
                summary["files_created"].append(f"videos/ ({video_count} files)")
        
        return summary
    
    def cleanup_empty_directories(self) -> None:
        """清理空目录"""
        try:
            for root, dirs, files in os.walk(self.base_path, topdown=False):
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    try:
                        if not os.listdir(dir_path):  # 目录为空
                            os.rmdir(dir_path)
                    except OSError:
                        pass  # 忽略删除失败的情况
        except OSError:
            pass  # 忽略遍历失败的情况
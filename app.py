#!/usr/bin/env python3
"""
Twitter内容保存工具 - Web界面
Flask + Bootstrap Web应用
"""

import os
import re
import json
import sqlite3
import subprocess
import threading
import time
import logging
import sys
import io
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory, Response, session, flash
from werkzeug.utils import secure_filename
import queue
from collections import deque
from services.config_manager import ConfigManager
from services.twitter_service import TwitterService, TwitterScrapingError
from services.media_downloader import MediaDownloader
from services.file_manager import FileManager
from services.user_manager import UserManager
from services.xhs_service import XHSService, XHSServiceError
from services.wechat_service import WechatService, WechatServiceError
from services.youtube_service import YoutubeService, YoutubeServiceError
from utils.url_parser import TwitterURLParser

app = Flask(__name__)

# Data directory — override with DATA_DIR env var (used by Docker)
DATA_DIR = os.environ.get('DATA_DIR', os.path.dirname(os.path.abspath(__file__)))

# 使用固定的 secret key 或从环境变量读取
# 这样重启应用后 session 不会失效
SECRET_KEY_FILE = os.path.join(DATA_DIR, 'secret_key.txt')
if os.path.exists(SECRET_KEY_FILE):
    with open(SECRET_KEY_FILE, 'r') as f:
        app.secret_key = f.read().strip()
else:
    # 首次运行，生成并保存 secret key
    app.secret_key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, 'w') as f:
        f.write(app.secret_key)

app.permanent_session_lifetime = timedelta(days=1)  # Default 24 hours

# Session 配置 - 确保在 HTTPS 环境下正常工作
app.config['SESSION_COOKIE_SECURE'] = False  # 允许 HTTP 和 HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # 防止 XSS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF 保护

# 配置日志级别，减少Flask的HTTP请求日志
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# 导入实时日志系统
from utils.realtime_logger import log_buffer, log_lock, log, info, error, warning, success

# 添加自定义Jinja2过滤器
@app.template_filter('tojsonpretty')
def to_json_pretty(value):
    """将对象转换为格式化的JSON字符串"""
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)

@app.template_filter('autolink')
def autolink(text):
    """自动将文本中的链接转换为HTML链接"""
    import re

    # 处理 None 或空字符串
    if not text:
        return ''

    # 确保是字符串类型
    text = str(text)

    # URL正则表达式
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'

    # 替换URL为链接
    def replace_url(match):
        url = match.group(0)
        # 截断显示的URL长度
        display_url = url if len(url) <= 50 else url[:47] + '...'
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="text-primary">{display_url}</a>'

    text = re.sub(url_pattern, replace_url, text)

    # 处理@用户名
    mention_pattern = r'@(\w+)'
    def replace_mention(match):
        username = match.group(1)
        return f'<a href="https://twitter.com/{username}" target="_blank" rel="noopener noreferrer" class="text-info">@{username}</a>'

    text = re.sub(mention_pattern, replace_mention, text)

    # 处理#标签
    hashtag_pattern = r'#(\w+)'
    def replace_hashtag(match):
        hashtag = match.group(1)
        return f'<a href="https://twitter.com/hashtag/{hashtag}" target="_blank" rel="noopener noreferrer" class="text-success">#{hashtag}</a>'

    text = re.sub(hashtag_pattern, replace_hashtag, text)

    return text

@app.template_filter('nl2br')
def nl2br(text):
    """将换行符转换为HTML换行"""
    if not text:
        return ''
    return str(text).replace('\n', '<br>')

@app.template_filter('format_datetime')
def format_datetime(datetime_str):
    """格式化日期时间"""
    if not datetime_str:
        return 'Unknown'
    try:
        # 尝试解析ISO格式的日期时间
        if 'T' in datetime_str:
            dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(datetime_str)
        return dt.strftime('%Y-%m-%d %H:%M')
    except:
        return datetime_str

# 添加context processor，自动传递登录状态给所有模板
@app.context_processor
def inject_user_status():
    """注入用户登录状态到所有模板"""
    return {
        'is_logged_in': session.get('logged_in', False),
        'username': session.get('username', None)
    }

# 全局变量
config_manager = None
twitter_service = None
media_downloader = None
file_manager = None
user_manager = UserManager(os.path.join(DATA_DIR, 'users.json'))  # Initialize UserManager
processing_queue = queue.Queue()
is_processing = False
_queued_task_ids = set()  # Track task IDs currently in the queue to prevent duplicates
_queued_task_ids_lock = threading.Lock()

def enqueue_task(task_id: int, url: str) -> bool:
    """Add a task to the processing queue. Returns False if already queued."""
    with _queued_task_ids_lock:
        if task_id in _queued_task_ids:
            return False
        _queued_task_ids.add(task_id)
    processing_queue.put((task_id, url))
    return True
processing_thread = None

# 登录验证装饰器
def login_required(f):
    """
    Decorator to require login for frontend routes
    API routes are exempt from login requirement
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if request is for API endpoint
        if request.path.startswith('/api/'):
            return f(*args, **kwargs)

        # Check if user is logged in
        if 'logged_in' not in session or not session['logged_in']:
            return redirect(url_for('login', next=request.url))

        return f(*args, **kwargs)
    return decorated_function

def normalize_path_cross_platform(path):
    """标准化路径以支持跨平台兼容性（Windows <-> Linux）"""
    if not path:
        return path
    
    # 根据当前操作系统标准化路径分隔符
    if os.sep == '/':  # Linux/Unix 系统
        normalized_path = path.replace('\\', '/')
    else:  # Windows 系统
        normalized_path = path.replace('/', '\\')
    
    # 使用 os.path.normpath 进一步标准化路径
    normalized_path = os.path.normpath(normalized_path)
    
    # 如果是相对路径，确保相对于当前工作目录
    if not os.path.isabs(normalized_path):
        normalized_path = os.path.join(os.getcwd(), normalized_path)
        normalized_path = os.path.normpath(normalized_path)
    
    return normalized_path

def find_actual_tweet_directory(expected_path):
    """查找实际存在的推文目录，处理日期不匹配问题"""
    if os.path.exists(expected_path):
        return expected_path
    
    # 如果期望路径不存在，尝试在父目录中查找匹配的目录
    parent_dir = os.path.dirname(expected_path)
    expected_basename = os.path.basename(expected_path)
    
    if not os.path.exists(parent_dir):
        return expected_path  # 返回原路径，调用者可以判断是否存在
    
    try:
        # 提取推文ID（格式通常是 YYYY-MM-DD_tweet_id）
        if '_' in expected_basename:
            date_part, tweet_id = expected_basename.split('_', 1)
            
            # 在父目录中查找包含相同推文ID的目录
            for item in os.listdir(parent_dir):
                item_path = os.path.join(parent_dir, item)
                if os.path.isdir(item_path) and '_' in item:
                    item_date, item_tweet_id = item.split('_', 1)
                    if item_tweet_id == tweet_id:
                        return item_path
        
        # 如果没找到精确匹配，尝试部分匹配
        for item in os.listdir(parent_dir):
            item_path = os.path.join(parent_dir, item)
            if os.path.isdir(item_path) and expected_basename in item:
                return item_path
                
    except Exception as e:
        pass
    
    return expected_path  # 如果找不到，返回原路径

def get_current_time():
    """获取当前时间，使用本地时区但保持一致性"""
    return datetime.now()

def format_time_for_db(dt):
    """格式化时间用于数据库存储"""
    if dt is None:
        return None
    return dt.isoformat()

def parse_time_from_db(time_str):
    """从数据库解析时间字符串"""
    if not time_str:
        return None
    try:
        return datetime.fromisoformat(time_str)
    except:
        # 兼容旧格式
        try:
            return datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        except:
            return None

def generate_unique_slug():
    """生成唯一的URL安全的随机字符串用于分享链接"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    max_attempts = 10
    for _ in range(max_attempts):
        # 生成8字符的URL安全随机字符串
        slug = secrets.token_urlsafe(8)
        
        # 检查是否已存在
        existing = cursor.execute(
            'SELECT id FROM tasks WHERE share_slug = ?',
            (slug,)
        ).fetchone()
        
        if not existing:
            conn.close()
            return slug
    
    conn.close()
    # 如果10次都冲突（几乎不可能），使用更长的字符串
    return secrets.token_urlsafe(12)


def check_and_schedule_retry(cursor, task_id, error_message):
    """检查任务是否应该重试，如果是则安排重试"""
    try:
        # 获取当前任务的重试信息
        task = cursor.execute(
            'SELECT retry_count, max_retries FROM tasks WHERE id = ?',
            (task_id,)
        ).fetchone()
        
        if not task:
            return False
        
        retry_count = task['retry_count'] if task['retry_count'] else 0
        max_retries = task['max_retries'] if task['max_retries'] else 3
        
        # 检查是否应该重试的错误类型
        retry_eligible_errors = [
            "Web scraping failed and API is not available",
            "Failed to fetch tweet",
            "Rate limit exceeded",
            "Timeout",
            "Connection error",
            "Request failed"
        ]
        
        should_retry = any(error_pattern in error_message for error_pattern in retry_eligible_errors)
        
        if should_retry and retry_count < max_retries:
            # 计算下次重试时间（指数退避：2^retry_count 分钟）
            delay_minutes = min(2 ** retry_count, 60)  # 最大延迟60分钟
            next_retry_time = get_current_time() + timedelta(minutes=delay_minutes)
            
            # 更新重试信息
            cursor.execute("""
                UPDATE tasks SET 
                    status = 'pending',
                    retry_count = ?,
                    next_retry_time = ?,
                    error_message = ?
                WHERE id = ?
            """, (
                retry_count + 1,
                format_time_for_db(next_retry_time),
                f"Retry {retry_count + 1}/{max_retries}: {error_message}",
                task_id
            ))
            
            print(f"[Task {task_id}] Scheduled for retry {retry_count + 1}/{max_retries} at {next_retry_time.strftime('%Y-%m-%d %H:%M:%S')}")
            return True
        else:
            print(f"[Task {task_id}] Max retries ({max_retries}) reached or error not retry-eligible")
            return False
            
    except Exception as e:
        print(f"Error in check_and_schedule_retry: {e}")
        return False

def check_retry_ready_tasks():
    """检查并将准备重试的任务重新加入队列"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查找到达重试时间的任务
        current_time = get_current_time()
        cursor.execute("""
            SELECT id, url FROM tasks 
            WHERE status = 'pending' 
            AND next_retry_time IS NOT NULL 
            AND next_retry_time <= ?
            AND retry_count > 0
        """, (format_time_for_db(current_time),))
        
        retry_tasks = cursor.fetchall()
        
        for task in retry_tasks:
            task_id, url = task['id'], task['url']
            info(f"[Retry Queue] Adding retry task {task_id} to queue: {url}")
            enqueue_task(task_id, url)
            
            # 清除next_retry_time以避免重复加入队列
            cursor.execute(
                "UPDATE tasks SET next_retry_time = NULL WHERE id = ?",
                (task_id,)
            )
        
        if retry_tasks:
            conn.commit()
            info(f"[Retry Queue] Added {len(retry_tasks)} retry tasks to queue")
        
        conn.close()
        
    except Exception as e:
        error(f"Error in check_retry_ready_tasks: {e}")

def check_and_queue_pending_tasks():
    """检查所有pending任务并确保它们在队列中（防止重置后任务丢失）"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查找所有pending状态且没有重试时间的任务（通常是重置后的任务）
        cursor.execute("""
            SELECT id, url FROM tasks 
            WHERE status = 'pending' 
            AND (next_retry_time IS NULL OR (retry_count = 0 AND next_retry_time IS NULL))
        """)
        
        pending_tasks = cursor.fetchall()
        
        if pending_tasks:
            added = 0
            for task in pending_tasks:
                if enqueue_task(task['id'], task['url']):
                    info(f"[Pending Check] Added pending task {task['id']} to queue: {task['url']}")
                    added += 1
            if added:
                info(f"[Pending Check] Added {added} pending tasks to queue")
        
        conn.close()
        
    except Exception as e:
        error(f"Error in check_and_queue_pending_tasks: {e}")

# 数据库初始化
def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(os.path.join(DATA_DIR, 'twitter_saver.db'))
    cursor = conn.cursor()
    
    # 创建任务表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            tweet_id TEXT,
            author_username TEXT,
            author_name TEXT,
            save_path TEXT,
            error_message TEXT,
            is_thread BOOLEAN DEFAULT FALSE,
            tweet_count INTEGER DEFAULT 0,
            media_count INTEGER DEFAULT 0,
            tweet_text TEXT,
            retry_count INTEGER DEFAULT 0,
            next_retry_time TIMESTAMP,
            max_retries INTEGER DEFAULT 3
        )
    ''')
    
    # 添加新字段（用于已有数据库的升级）
    new_columns = [
        ('tweet_text', 'TEXT'),
        ('retry_count', 'INTEGER DEFAULT 0'),
        ('next_retry_time', 'TIMESTAMP'),
        ('max_retries', 'INTEGER DEFAULT 3'),
        ('share_slug', 'TEXT'),
        ('content_type', "TEXT DEFAULT 'tweet'")
    ]
    
    for column_name, column_def in new_columns:
        try:
            cursor.execute(f'ALTER TABLE tasks ADD COLUMN {column_name} {column_def}')
        except sqlite3.OperationalError:
            # 字段已存在，忽略错误
            pass
    
    # 创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tweet_id ON tasks(tweet_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_author_username ON tasks(author_username)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_author_name ON tasks(author_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_next_retry_time ON tasks(next_retry_time)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_retry_count ON tasks(retry_count)')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_share_slug ON tasks(share_slug)')

    # App settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    # Default XHS auto-save settings
    cursor.executemany(
        'INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)',
        [
            ('xhs_autosave_enabled', 'false'),
            ('xhs_autosave_interval_minutes', '30'),
            ('xhs_autosave_last_run', ''),
            ('xhs_autosave_last_count', '0'),
            ('xhs_user_id', ''),
        ]
    )

    # FTS5 full-text search table (trigram tokenizer for CJK substring matching)
    # Recreate if schema changed (e.g. added trigram, switched to content-storing)
    _fts_exists = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks_fts'"
    ).fetchone()
    _need_recreate = _fts_exists and ("content=''" in (_fts_exists[0] or '') or 'trigram' not in (_fts_exists[0] or ''))
    if _need_recreate:
        cursor.execute('DROP TABLE IF EXISTS tasks_fts')
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
            author_name,
            author_username,
            full_text,
            content_rowid='id',
            tokenize='trigram'
        )
    ''')

    conn.commit()
    conn.close()


def fts_upsert(conn, task_id, author_name, author_username, full_text):
    """Insert or replace a row in the FTS5 index."""
    # Delete old entry if exists, then insert new one
    conn.execute('DELETE FROM tasks_fts WHERE rowid = ?', (task_id,))
    conn.execute('INSERT INTO tasks_fts(rowid, author_name, author_username, full_text) VALUES(?, ?, ?, ?)',
                 (task_id, author_name or '', author_username or '', full_text or ''))


def _read_full_text(save_path):
    """Read full text from content.txt for FTS indexing."""
    if not save_path:
        return ''
    content_path = os.path.join(save_path, 'content.txt')
    if os.path.exists(content_path):
        try:
            with open(content_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception:
            pass
    return ''


def rebuild_fts_index():
    """Rebuild the FTS5 index from all completed tasks."""
    conn = get_db_connection()
    # Clear existing index
    conn.execute("DELETE FROM tasks_fts")

    tasks = conn.execute(
        "SELECT id, author_name, author_username, save_path, tweet_text FROM tasks WHERE status='completed'"
    ).fetchall()

    count = 0
    for t in tasks:
        full_text = _read_full_text(t['save_path']) or t['tweet_text'] or ''
        if full_text:
            conn.execute(
                'INSERT INTO tasks_fts(rowid, author_name, author_username, full_text) VALUES(?, ?, ?, ?)',
                (t['id'], t['author_name'] or '', t['author_username'] or '', full_text)
            )
            count += 1

    conn.commit()
    conn.close()
    return count


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(os.path.join(DATA_DIR, 'twitter_saver.db'))
    conn.row_factory = sqlite3.Row
    return conn

def init_services():
    """初始化服务"""
    global config_manager, twitter_service, media_downloader, file_manager
    
    try:
        print(f"[init_services] Starting service initialization...")
        print(f"[init_services] Current global variables: config_manager={config_manager}, twitter_service={twitter_service}")
        
        print(f"[init_services] Creating ConfigManager...")
        config_manager = ConfigManager()
        print(f"[init_services] ConfigManager created: {config_manager}")
        
        print(f"[init_services] Validating config...")
        if not config_manager.validate_config():
            print(f"[init_services] Config validation failed!")
            return False
        print(f"[init_services] Config validation passed")
        
        print(f"[init_services] Loading config...")
        config = config_manager.load_config()
        print(f"[init_services] Config loaded successfully")
        
        print(f"[init_services] Creating TwitterService...")
        twitter_service = TwitterService(
            max_retries=config['max_retries'],
            timeout=config['timeout_seconds'],
            use_playwright=config.get('use_playwright', True)
        )
        print(f"[init_services] TwitterService created: {twitter_service}")
        
        print(f"[init_services] Creating MediaDownloader...")
        media_downloader = MediaDownloader(
            max_retries=config['max_retries'],
            timeout=config['timeout_seconds']
        )
        print(f"[init_services] MediaDownloader created: {media_downloader}")
        
        print(f"[init_services] Creating FileManager...")
        file_manager = FileManager(
            base_path=config['save_path'],
            create_date_folders=config['create_date_folders']
        )
        print(f"[init_services] FileManager created: {file_manager}")
        
        print(f"[init_services] All services created successfully!")
        print(f"[init_services] Final global variables: config_manager={config_manager}, twitter_service={twitter_service}")
        return True
    except Exception as e:
        print(f"[init_services] ERROR: Failed to initialize services: {e}")
        import traceback
        traceback.print_exc()
        return False

def process_xhs_task(task_id: int, url: str):
    """Queue worker handler for XiaoHongShu tasks."""
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        xhs = make_xhs_service()
        result = xhs.save_post(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?,
               author_username=?, author_name=?, save_path=?, tweet_text=?,
               share_slug=?, media_count=? WHERE id=?''',
            (now, result['feed_id'],
             result.get('author_username', ''), result.get('author_name', ''),
             result['save_path'], result.get('tweet_text', '')[:500],
             slug, result.get('media_count', result.get('image_count', 0)),
             task_id)
        )
        full_text = _read_full_text(result['save_path']) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''), full_text)
        conn.commit()
        conn.close()
        success(f'[XHS Task {task_id}] Saved: {result["title"]}')
    except Exception as e:
        error(f'[XHS Task {task_id}] Failed: {e}')
        try:
            conn2 = get_db_connection()
            conn2.execute(
                "UPDATE tasks SET status='failed', error_message=? WHERE id=?",
                (str(e)[:500], task_id)
            )
            conn2.commit()
            conn2.close()
        except Exception:
            pass


def process_wechat_task(task_id: int, url: str):
    """Queue worker handler for WeChat article tasks."""
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        wechat = make_wechat_service()
        result = wechat.save_article(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?,
               author_username=?, author_name=?, save_path=?, tweet_text=?,
               share_slug=?, media_count=? WHERE id=?''',
            (now, result.get('article_id', ''),
             result.get('author_username', ''), result.get('author_name', ''),
             result.get('save_path', ''), result.get('tweet_text', '')[:500],
             slug, result.get('image_count', 0),
             task_id)
        )
        full_text = _read_full_text(result.get('save_path', '')) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''), full_text)
        conn.commit()
        conn.close()
        success(f'[WeChat Task {task_id}] Saved: {result["title"]}')
    except Exception as e:
        error(f'[WeChat Task {task_id}] Failed: {e}')
        try:
            conn2 = get_db_connection()
            conn2.execute(
                "UPDATE tasks SET status='failed', error_message=? WHERE id=?",
                (str(e)[:500], task_id)
            )
            conn2.commit()
            conn2.close()
        except Exception:
            pass


def process_youtube_task(task_id: int, url: str):
    """Queue worker handler for YouTube tasks."""
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        youtube = make_youtube_service()
        result = youtube.save_video(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?,
               author_username=?, author_name=?, save_path=?, tweet_text=?,
               share_slug=?, media_count=? WHERE id=?''',
            (now, result['video_id'],
             result.get('author_username', ''), result.get('author_name', ''),
             result['save_path'], result.get('title', '')[:500],
             slug, 1,
             task_id)
        )
        full_text = _read_full_text(result['save_path']) or result.get('title', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''), full_text)
        conn.commit()
        conn.close()
        success(f'[YouTube Task {task_id}] Saved: {result["title"]}')
    except Exception as e:
        error(f'[YouTube Task {task_id}] Failed: {e}')
        try:
            conn2 = get_db_connection()
            conn2.execute(
                "UPDATE tasks SET status='failed', error_message=? WHERE id=?",
                (str(e)[:500], task_id)
            )
            conn2.commit()
            conn2.close()
        except Exception:
            pass


def process_tweet_task(task_id, url):
    """处理单个推文任务"""
    conn = get_db_connection()
    
    try:
        info(f"[Task {task_id}] Starting processing: {url}")
        update_task_progress(task_id, 'started', f'开始处理任务: {url}')
        
        # 先验证任务状态，确保任务还是pending状态
        task_check = conn.execute(
            'SELECT status FROM tasks WHERE id = ?', (task_id,)
        ).fetchone()
        
        if not task_check or task_check['status'] != 'pending':
            warning(f"[Task {task_id}] Task is not in pending status, skipping...")
            update_task_progress(task_id, 'skipped', '任务状态不是pending，跳过处理')
            conn.close()
            return
        
        # 更新任务状态为处理中
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        info(f"[Task {task_id}] Status updated to processing")
        update_task_progress(task_id, 'processing', '任务状态已更新为处理中')
        
        # 验证URL
        if not TwitterURLParser.is_valid_twitter_url(url):
            raise ValueError(f"Invalid Twitter URL: {url}")
        
        # 提取推文ID
        tweet_id = twitter_service.extract_tweet_id(url)
        info(f"[Task {task_id}] Extracted tweet ID: {tweet_id}")
        
        # 获取推文数据
        try:
            info(f"[Task {task_id}] Calling Twitter service to get tweet...")
            update_task_progress(task_id, 'api_call', f'正在获取推文 {tweet_id}')
            
            # 先尝试获取单个推文，传递完整URL保留用户名信息
            single_tweet = twitter_service.get_tweet(url)
            success(f"[Task {task_id}] Successfully got tweet from @{single_tweet.author_username}")
            update_task_progress(task_id, 'api_success', f'成功获取推文，作者: @{single_tweet.author_username}')
            
            # 检测是否为长文
            is_article = TwitterURLParser.is_article_url(url)
            content_type = 'article' if is_article else 'tweet'
            if is_article:
                info(f"[Task {task_id}] Detected article URL, will scrape full article content")
                update_task_progress(task_id, 'article_detected', '检测到长文链接，将抓取长文内容')

            tweets = [single_tweet]
            is_thread = False
                
        except TwitterScrapingError as e:
            error(f"[Task {task_id}] Twitter API Error: {str(e)}")
            if "Rate limit exceeded" in str(e):
                warning(f"[Task {task_id}] Rate limit exceeded, requeueing task...")
                current_time = get_current_time()
                retry_time = current_time.strftime('%H:%M:%S')
                next_retry = (current_time.timestamp() + 60)
                next_retry_str = datetime.fromtimestamp(next_retry).strftime('%H:%M:%S')
                
                update_task_progress(
                    task_id, 
                    'rate_limited', 
                    f'API速率限制，将在 {next_retry_str} 重试',
                    error_message=f'Rate limit exceeded at {retry_time}',
                    retry_time=next_retry_str
                )
                
                # 速率限制，将任务重新放回队列
                conn.execute(
                    'UPDATE tasks SET status = ?, error_message = ? WHERE id = ?',
                    ('pending', f'Rate limit exceeded at {retry_time}, will retry at {next_retry_str}', task_id)
                )
                conn.commit()
                conn.close()
                # 使用定时器延迟重新加入队列，不阻塞当前线程
                info(f"[Task {task_id}] Scheduling retry in 60 seconds...")
                def delayed_requeue():
                    enqueue_task(task_id, url)
                    info(f"[Task {task_id}] Requeued after rate limit delay")
                
                timer = threading.Timer(60.0, delayed_requeue)
                timer.start()
                return
            else:
                error(f"[Task {task_id}] Non-rate-limit API error: {str(e)}")
                update_task_progress(task_id, 'api_error', f'API调用失败: {str(e)}', error_message=str(e))
                raise e
        
        # 创建保存目录
        save_dir = file_manager.create_save_directory(tweets[0].id, tweets[0].created_at)
        update_task_progress(task_id, 'saving', f'创建保存目录: {save_dir}')
        
        # 统计媒体文件数量
        total_images = sum(len(tweet.get_images()) for tweet in tweets)
        total_videos = sum(len(tweet.get_videos()) for tweet in tweets)
        total_avatars = sum(len(tweet.get_avatars()) for tweet in tweets)
        total_media = total_images + total_videos + total_avatars
        
        if total_media > 0:
            update_task_progress(task_id, 'media_download', f'准备下载 {total_media} 个媒体文件 (图片:{total_images}, 视频:{total_videos}, 头像:{total_avatars})')
        
        # 下载媒体文件
        all_media_files = []
        downloaded_count = 0
        
        for tweet in tweets:
            if tweet.has_media():
                images = tweet.get_images()
                videos = tweet.get_videos()
                avatars = tweet.get_avatars()
                
                if images:
                    update_task_progress(task_id, 'downloading_images', f'正在下载图片 ({len(images)} 个)...')
                    image_files = media_downloader.download_images(images, save_dir)
                    all_media_files.extend(image_files)
                    downloaded_count += len(image_files)
                    update_task_progress(task_id, 'images_done', f'图片下载完成 ({len(image_files)}/{len(images)})')
                
                if videos:
                    update_task_progress(task_id, 'downloading_videos', f'正在下载视频 ({len(videos)} 个)...')
                    video_files = media_downloader.download_videos(videos, save_dir)
                    all_media_files.extend(video_files)
                    downloaded_count += len(video_files)
                    update_task_progress(task_id, 'videos_done', f'视频下载完成 ({len(video_files)}/{len(videos)})')
                
                if avatars:
                    update_task_progress(task_id, 'downloading_avatars', f'正在下载头像 ({len(avatars)} 个)...')
                    avatar_files = media_downloader.download_avatars(avatars, save_dir)
                    all_media_files.extend(avatar_files)
                    downloaded_count += len(avatar_files)
                    update_task_progress(task_id, 'avatars_done', f'头像下载完成 ({len(avatar_files)}/{len(avatars)})')
        
        if total_media > 0:
            update_task_progress(task_id, 'media_complete', f'媒体下载完成: {downloaded_count}/{total_media} 个文件')
        
        # 保存推文内容
        if len(tweets) == 1:
            file_manager.save_tweet_content(tweets[0], save_dir, all_media_files)
        else:
            file_manager.save_thread_content(tweets, save_dir, all_media_files)
        
        # 保存元数据
        file_manager.save_metadata(tweets, save_dir, all_media_files)
        
        # 构建推文文本内容（用于搜索）
        if len(tweets) == 1:
            # 单条推文
            tweet_text = tweets[0].text
        else:
            # 推文串：合并所有推文文本，用双换行分隔
            tweet_text = '\n\n'.join(tweet.text for tweet in tweets)
        
        # 生成唯一的分享slug
        share_slug = generate_unique_slug()
        
        # 更新任务状态为完成
        conn.execute('''
            UPDATE tasks SET 
                status = ?, 
                tweet_id = ?, 
                author_username = ?, 
                author_name = ?, 
                save_path = ?, 
                is_thread = ?, 
                tweet_count = ?, 
                media_count = ?,
                tweet_text = ?,
                share_slug = ?,
                content_type = ?,
                error_message = NULL
            WHERE id = ?
        ''', (
            'completed',
            tweets[0].id,
            tweets[0].author_username,
            tweets[0].author_name,
            save_dir,
            is_thread,
            len(tweets),
            len(all_media_files),
            tweet_text,
            share_slug,
            content_type,
            task_id
        ))
        conn.commit()

        # Update FTS index
        full_text = _read_full_text(save_dir) or tweet_text
        fts_upsert(conn, task_id, tweets[0].author_name, tweets[0].author_username, full_text)
        conn.commit()

        info(f"[Task {task_id}] Generated share slug: {share_slug}")


    except Exception as e:
        # 检查是否应该重试
        should_retry = check_and_schedule_retry(conn.cursor(), task_id, str(e))
        if not should_retry:
            # 不重试，更新任务状态为失败
            conn.execute(
                'UPDATE tasks SET status = ?, error_message = ? WHERE id = ?',
                ('failed', str(e), task_id)
            )
        conn.commit()
    
    finally:
        conn.close()

def queue_processor():
    """队列处理器"""
    global is_processing
    
    info("[Queue Processor] Starting queue processor thread...")
    
    while True:
        try:
            # 检查是否有待重试的任务
            check_retry_ready_tasks()

            # 检查是否有pending任务需要加入队列（每30秒检查一次）
            import time
            if not hasattr(check_and_queue_pending_tasks, 'last_check'):
                check_and_queue_pending_tasks.last_check = 0

            current_time = time.time()
            if current_time - check_and_queue_pending_tasks.last_check > 30:
                check_and_queue_pending_tasks()
                check_and_queue_pending_tasks.last_check = current_time

            # 从队列获取任务
            if processing_queue.qsize() > 0:
                info(f"[Queue Processor] Queue has {processing_queue.qsize()} tasks, getting next task...")
            
            task_id, url = processing_queue.get(timeout=5)  # 增加超时时间
            is_processing = True

            # Remove from queued set IMMEDIATELY after dequeue, before any DB calls
            # This prevents task_id from being stuck in _queued_task_ids if DB lookup fails
            with _queued_task_ids_lock:
                _queued_task_ids.discard(task_id)

            # Look up content_type to dispatch to the right handler
            _ct_conn = get_db_connection()
            _ct_row = _ct_conn.execute(
                'SELECT content_type FROM tasks WHERE id = ?', (task_id,)
            ).fetchone()
            _ct_conn.close()
            _content_type = (_ct_row['content_type'] if _ct_row else None) or 'tweet'

            info(f"[Queue Processor] Got task {task_id} ({_content_type}): {url}")
            info(f"[Queue Processor] Starting to process task {task_id}...")

            task_success = False
            try:

                # Guard: skip if task is no longer pending (duplicate queue entry)
                _guard_conn = get_db_connection()
                _guard_row = _guard_conn.execute(
                    'SELECT status FROM tasks WHERE id = ?', (task_id,)
                ).fetchone()
                _guard_conn.close()
                if not _guard_row or _guard_row['status'] not in ('pending',):
                    warning(f"[Queue Processor] Task {task_id} status is '{_guard_row['status'] if _guard_row else 'unknown'}', skipping (duplicate or already processed)")
                    processing_queue.task_done()
                    is_processing = False
                    continue

                if _content_type == 'xhs':
                    process_xhs_task(task_id, url)
                elif _content_type == 'wechat':
                    process_wechat_task(task_id, url)
                elif _content_type == 'youtube':
                    process_youtube_task(task_id, url)
                else:
                    process_tweet_task(task_id, url)
                # 检查任务实际状态来确定是否成功
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT status FROM tasks WHERE id = ?', (task_id,))
                result = cursor.fetchone()
                conn.close()
                
                if result and result[0] == 'completed':
                    success(f"[Queue Processor] Successfully processed task {task_id}")
                    task_success = True
                else:
                    warning(f"[Queue Processor] Task {task_id} not completed (status: {result[0] if result else 'unknown'})")
                    
            except Exception as task_error:
                error(f"[Queue Processor] Error processing task {task_id}: {task_error}")
                import traceback
                traceback.print_exc()
                
                # 错误处理现在在process_tweet_task中处理重试逻辑
                warning(f"[Queue Processor] Task {task_id} error handled by process_tweet_task")
            
            processing_queue.task_done()
            is_processing = False
            
            if task_success:
                success(f"[Queue Processor] Completed processing task {task_id}")
            else:
                warning(f"[Queue Processor] Finished processing task {task_id} (may have failed or scheduled for retry)")
            
            # 处理完一个任务后稍作休息
            time.sleep(2)
            
        except queue.Empty:
            is_processing = False
            # 减少日志输出频率 - 只在首次空队列时输出
            continue
        except Exception as e:
            error(f"[Queue Processor] Unexpected error in queue processor: {e}")
            import traceback
            traceback.print_exc()
            is_processing = False
            time.sleep(5)  # 遇到异常时等待5秒再继续

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面和处理"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember_days = request.form.get('remember_days', '1', type=int)

        if not username or not password:
            return render_template('login.html', error='Username and password are required')

        # 验证用户
        if user_manager.authenticate(username, password):
            # 设置session
            session.permanent = True
            session['logged_in'] = True
            session['username'] = username

            # 设置session有效期
            app.permanent_session_lifetime = timedelta(days=remember_days)

            # 重定向到原页面或主页
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('saved'))
        else:
            return render_template('login.html', error='Invalid username or password')

    # GET请求，显示登录表单
    return render_template('login.html')

@app.route('/logout')
def logout():
    """退出登录"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change password page"""
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not current_password or not new_password or not confirm_password:
            return render_template('change_password.html', error='All fields are required')

        if new_password != confirm_password:
            return render_template('change_password.html', error='New passwords do not match')

        username = session.get('username')
        if user_manager.change_password(username, current_password, new_password):
            session.clear()
            return redirect(url_for('login'))
        else:
            return render_template('change_password.html', error='Current password is incorrect')

    return render_template('change_password.html')

@app.route('/')
@login_required
def index():
    """主页 - 重定向到已保存推文页面"""
    return redirect(url_for('saved'))

@app.route('/status')
@login_required
def status_page():
    """状态页面 - 显示系统状态和提交界面"""
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
@login_required
def submit_url():
    """提交URL - 支持 Twitter/X, YouTube, XHS, WeChat"""
    url = request.form.get('url', '').strip()

    if not url:
        return jsonify({'success': False, 'message': 'URL is required'})

    # Detect content type
    content_type = 'tweet'
    if YoutubeService.is_valid_youtube_url(url):
        content_type = 'youtube'
    elif XHSService.is_valid_xhs_url(url):
        content_type = 'xhs'
    elif WechatService.is_valid_wechat_url(url):
        content_type = 'wechat'
    elif TwitterURLParser.is_valid_twitter_url(url):
        content_type = 'tweet'
    else:
        # Try XHS share text extraction
        extracted = XHSService.extract_url_from_share_text(url)
        if extracted and XHSService.is_valid_xhs_url(extracted):
            url = extracted
            content_type = 'xhs'
        else:
            return jsonify({'success': False, 'message': 'Unsupported URL. Supported: Twitter/X, YouTube, XiaoHongShu, WeChat articles'})

    # Normalize XHS URL
    if content_type == 'xhs':
        url = XHSService.resolve_xhslink(url)
        url = XHSService.normalize_xhs_url(url)

    # 检查是否已经存在相同的URL
    conn = get_db_connection()
    existing = conn.execute(
        'SELECT id FROM tasks WHERE url = ? AND status != "failed"',
        (url,)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({'success': False, 'message': 'This URL is already in the queue'})

    # 添加到数据库
    now = format_time_for_db(get_current_time())
    cursor = conn.execute(
        'INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, ?, ?, ?)',
        (url, 'pending', now, content_type)
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # 添加到处理队列
    enqueue_task(task_id, url)
    info(f"[Submit] Added {content_type} task {task_id} to queue. Queue size: {processing_queue.qsize()}")

    return jsonify({'success': True, 'message': f'{content_type.capitalize()} URL added to queue', 'task_id': task_id})

@app.route('/api/status')
def status():
    """获取系统状态"""
    conn = get_db_connection()
    
    # 获取各状态的任务数量
    stats = conn.execute('''
        SELECT status, COUNT(*) as count 
        FROM tasks 
        GROUP BY status
    ''').fetchall()
    
    status_counts = {row['status']: row['count'] for row in stats}
    
    # 获取队列大小 - 统计所有待处理和处理中的任务
    # 这样显示更准确：正在处理的任务也会被计入
    pending_and_processing = conn.execute('''
        SELECT COUNT(*) as count 
        FROM tasks 
        WHERE status IN ('pending', 'processing')
    ''').fetchone()
    queue_size = pending_and_processing['count'] if pending_and_processing else 0
    
    # 获取最近的任务状态
    recent_tasks = conn.execute('''
        SELECT id, url, status, error_message, created_at, processed_at
        FROM tasks 
        ORDER BY created_at DESC 
        LIMIT 5
    ''').fetchall()
    
    recent_tasks_list = []
    for task in recent_tasks:
        task_dict = dict(task)
        if task_dict['created_at']:
            created_time = parse_time_from_db(task_dict['created_at'])
            task_dict['created_at'] = created_time.strftime('%H:%M:%S') if created_time else task_dict['created_at']
        if task_dict['processed_at']:
            processed_time = parse_time_from_db(task_dict['processed_at'])
            task_dict['processed_at'] = processed_time.strftime('%H:%M:%S') if processed_time else task_dict['processed_at']
        recent_tasks_list.append(task_dict)
    
    conn.close()
    
    return jsonify({
        'queue_size': queue_size,
        'is_processing': is_processing,
        'status_counts': status_counts,
        'recent_tasks': recent_tasks_list,
        'processing_thread_alive': processing_thread.is_alive() if processing_thread else False
    })

@app.route('/tasks')
@login_required
def tasks():
    """任务列表页面"""
    return render_template('tasks.html')

@app.route('/api/tasks')
def api_tasks():
    """获取任务列表API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status_filter = request.args.get('status', '')
    
    conn = get_db_connection()
    
    # 构建查询
    where_clause = ''
    params = []
    
    if status_filter:
        where_clause = 'WHERE status = ?'
        params.append(status_filter)
    
    # 获取总数
    total_query = f'SELECT COUNT(*) as count FROM tasks {where_clause}'
    total = conn.execute(total_query, params).fetchone()['count']
    
    # 获取分页数据
    offset = (page - 1) * per_page
    tasks_query = f'''
        SELECT * FROM tasks {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    '''
    params.extend([per_page, offset])
    
    tasks = conn.execute(tasks_query, params).fetchall()
    conn.close()
    
    # 转换为字典列表
    tasks_list = []
    for task in tasks:
        task_dict = dict(task)
        # 格式化时间
        if task_dict['created_at']:
            created_time = parse_time_from_db(task_dict['created_at'])
            task_dict['created_at'] = created_time.strftime('%Y-%m-%d %H:%M:%S') if created_time else task_dict['created_at']
        if task_dict['processed_at']:
            processed_time = parse_time_from_db(task_dict['processed_at'])
            task_dict['processed_at'] = processed_time.strftime('%Y-%m-%d %H:%M:%S') if processed_time else task_dict['processed_at']
        tasks_list.append(task_dict)
    
    return jsonify({
        'tasks': tasks_list,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page
    })

@app.route('/saved')
@login_required
def saved():
    """已保存推文列表页面"""
    return render_template('saved.html')


@app.route('/retries')
@login_required
def retries():
    return redirect(url_for('tasks'))

@app.route('/api/saved')
def api_saved():
    """获取已保存推文列表API，支持搜索功能"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search_query = request.args.get('search', '').strip()
    
    conn = get_db_connection()
    
    # 构建搜索条件
    base_where = "status = 'completed'"
    params = []
    
    offset = (page - 1) * per_page

    if search_query:
        use_fts = len(search_query) >= 3
        if use_fts:
            # FTS5 trigram search (requires ≥3 unicode chars)
            fts_query = '"' + search_query.replace('"', '""') + '"'
            query = '''
                SELECT tasks.* FROM tasks
                JOIN tasks_fts ON tasks.id = tasks_fts.rowid
                WHERE tasks.status = 'completed' AND tasks_fts MATCH ?
                ORDER BY tasks.processed_at DESC
                LIMIT ? OFFSET ?
            '''
            params = [fts_query, per_page, offset]
            tasks = conn.execute(query, params).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) as count FROM tasks JOIN tasks_fts ON tasks.id = tasks_fts.rowid WHERE tasks.status = 'completed' AND tasks_fts MATCH ?",
                [fts_query]
            ).fetchone()['count']
        else:
            # Short query (<3 chars): trigram can't match, fallback to LIKE on FTS full_text
            like_param = f'%{search_query}%'
            query = '''
                SELECT tasks.* FROM tasks
                JOIN tasks_fts ON tasks.id = tasks_fts.rowid
                WHERE tasks.status = 'completed'
                  AND (tasks_fts.full_text LIKE ? OR tasks_fts.author_name LIKE ? OR tasks_fts.author_username LIKE ?)
                ORDER BY tasks.processed_at DESC
                LIMIT ? OFFSET ?
            '''
            params = [like_param, like_param, like_param, per_page, offset]
            tasks = conn.execute(query, params).fetchall()
            total = conn.execute(
                '''SELECT COUNT(*) as count FROM tasks
                   JOIN tasks_fts ON tasks.id = tasks_fts.rowid
                   WHERE tasks.status = 'completed'
                     AND (tasks_fts.full_text LIKE ? OR tasks_fts.author_name LIKE ? OR tasks_fts.author_username LIKE ?)''',
                [like_param, like_param, like_param]
            ).fetchone()['count']
    else:
        query = f'''
            SELECT * FROM tasks
            WHERE {base_where}
            ORDER BY processed_at DESC
            LIMIT ? OFFSET ?
        '''
        tasks = conn.execute(query, [per_page, offset]).fetchall()
        total = conn.execute(f"SELECT COUNT(*) as count FROM tasks WHERE {base_where}").fetchone()['count']
    
    conn.close()
    
    # 转换为字典列表
    saved_list = []
    for task in tasks:
        task_dict = dict(task)
        if task_dict['processed_at']:
            processed_time = parse_time_from_db(task_dict['processed_at'])
            task_dict['processed_at'] = processed_time.strftime('%Y-%m-%d %H:%M:%S') if processed_time else task_dict['processed_at']
        
        # 检查头像文件是否存在
        if task_dict['save_path']:
            # 使用通用函数标准化路径
            raw_path = task_dict['save_path']
            normalized_save_path = normalize_path_cross_platform(raw_path)
            
            # 查找实际存在的目录（处理日期不匹配问题）
            actual_save_path = find_actual_tweet_directory(normalized_save_path)
            
            # 使用实际找到的路径进行文件操作
            avatar_path = os.path.join(actual_save_path, 'avatar.jpg')
            ct = task_dict.get('content_type') or 'tweet'

            if os.path.exists(avatar_path):
                task_dict['has_avatar'] = True
                task_dict['avatar_url'] = f'/media/{task_dict["id"]}/avatar.jpg'
            elif ct == 'youtube':
                # Use thumbnail as avatar for YouTube
                thumb_dir = os.path.join(actual_save_path, 'thumbnails')
                thumb_file = None
                for ext in ('jpg', 'jpeg', 'png', 'webp'):
                    candidate = os.path.join(thumb_dir, f'cover.{ext}')
                    if os.path.exists(candidate):
                        thumb_file = f'thumbnails/cover.{ext}'
                        break
                if thumb_file:
                    task_dict['has_avatar'] = True
                    task_dict['avatar_url'] = f'/media/{task_dict["id"]}/{thumb_file}'
                else:
                    task_dict['has_avatar'] = False
                    task_dict['avatar_url'] = None
            else:
                task_dict['has_avatar'] = False
                task_dict['avatar_url'] = None
                
            # 检查是否有实际的媒体文件（不包括头像）用于预览
            has_media_preview = False
            
            # 检查是否有视频缩略图
            thumbnails_dir = os.path.join(actual_save_path, 'thumbnails')
            if os.path.exists(thumbnails_dir):
                for filename in os.listdir(thumbnails_dir):
                    if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                        has_media_preview = True
                        break
            
            # 如果没有缩略图，检查是否有图片
            if not has_media_preview:
                images_dir = os.path.join(actual_save_path, 'images')
                if os.path.exists(images_dir):
                    for filename in os.listdir(images_dir):
                        if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                            has_media_preview = True
                            break
            
            # 如果没有图片，检查是否有视频
            if not has_media_preview:
                videos_dir = os.path.join(actual_save_path, 'videos')
                if os.path.exists(videos_dir):
                    for filename in os.listdir(videos_dir):
                        if filename.lower().endswith(('.mp4', '.mov', '.avi', '.webm')):
                            has_media_preview = True
                            break
            
            task_dict['has_media_preview'] = has_media_preview
                
            # 读取推文内容用于预览（现在content.txt只包含纯文本）
            content_path = os.path.join(actual_save_path, 'content.txt')
            _ct = task_dict.get('content_type') or 'tweet'

            # YouTube / WeChat: show title as preview
            if _ct == 'youtube':
                task_dict['preview_text'] = task_dict.get('tweet_text') or ''
            elif _ct == 'wechat':
                meta_path = os.path.join(actual_save_path, 'metadata.json')
                title = ''
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, 'r', encoding='utf-8') as f:
                            title = json.load(f).get('title', '')
                    except Exception:
                        pass
                task_dict['preview_text'] = title or task_dict.get('tweet_text') or ''
            elif os.path.exists(content_path):
                try:
                    with open(content_path, 'r', encoding='utf-8') as f:
                        tweet_content = f.read().strip()
                        if tweet_content:
                            task_dict['preview_text'] = tweet_content[:140] + ('...' if len(tweet_content) > 140 else '')
                        else:
                            task_dict['preview_text'] = task_dict.get('tweet_text') or ''
                except Exception as e:
                    task_dict['preview_text'] = f'Failed to read content: {str(e)}'
            else:
                task_dict['preview_text'] = f'Content file not found: {content_path}'
        else:
            task_dict['has_avatar'] = False
            task_dict['avatar_url'] = None
            task_dict['has_media_preview'] = False
            task_dict['preview_text'] = 'Save path not found'

        saved_list.append(task_dict)

    return jsonify({
        'saved': saved_list,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page
    })



@app.route('/view/<slug>')
def show_tweet(slug):
    """显示推文 - 仅支持随机slug访问 (无需登录，可分享)"""
    # 调试：打印登录状态
    is_logged_in = session.get('logged_in', False)
    print(f"[DEBUG] /view/{slug} - is_logged_in: {is_logged_in}, session: {dict(session)}")

    # 获取任务信息 - 仅通过slug查找，不支持数字ID
    conn = get_db_connection()
    
    task = conn.execute(
        'SELECT * FROM tasks WHERE share_slug = ? AND status = "completed"',
        (slug,)
    ).fetchone()
    
    conn.close()
    
    if not task:
        return "Tweet not found", 404
    
    # 获取任务ID用于后续媒体文件访问
    task_id = task['id']
    
    # 扫描媒体文件
    media_files = []
    avatar_file = None
    save_path = task['save_path']
    # 使用通用函数标准化路径
    normalized_save_path = normalize_path_cross_platform(save_path)
    # 查找实际存在的目录
    actual_save_path = find_actual_tweet_directory(normalized_save_path)
    
    
    # 检查头像文件
    avatar_path = os.path.join(actual_save_path, 'avatar.jpg')
    if os.path.exists(avatar_path):
        avatar_file = {
            'filename': 'avatar.jpg',
            'type': 'avatar',
            'url': f'/media/{task_id}/avatar.jpg'
        }
    
    # 扫描images目录
    images_dir = os.path.join(actual_save_path, 'images')
    if os.path.exists(images_dir):
        for filename in sorted(os.listdir(images_dir)):
            if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                media_files.append({
                    'filename': filename,
                    'type': 'image',
                    'url': f'/media/{task_id}/images/{filename}'
                })
    
    # 扫描videos目录
    videos_dir = os.path.join(actual_save_path, 'videos')
    if os.path.exists(videos_dir):
        for filename in os.listdir(videos_dir):
            if filename.lower().endswith(('.mp4', '.mov', '.avi', '.webm')):
                media_files.append({
                    'filename': filename,
                    'type': 'video',
                    'url': f'/media/{task_id}/videos/{filename}'
                })
    
    # 读取推文文本内容
    tweet_text = ""
    content_txt_file = os.path.join(actual_save_path, 'content.txt')
    if os.path.exists(content_txt_file):
        try:
            with open(content_txt_file, 'r', encoding='utf-8') as f:
                tweet_text = f.read().strip()
        except Exception as e:
            print(f"[DEBUG] Failed to read content.txt: {e}")
            tweet_text = ""

    # 读取Reader模式HTML内容
    tweet_html = ""
    content_html_file = os.path.join(actual_save_path, 'content.html')
    if os.path.exists(content_html_file):
        try:
            with open(content_html_file, 'r', encoding='utf-8') as f:
                html_content = f.read()
                # 提取HTML文件中的推文内容部分（去掉HTML文档结构）
                # 提取<div class="reader-content">内的内容
                content_match = re.search(r'<div class="reader-content">(.*?)</div>', html_content, re.DOTALL)
                if content_match:
                    tweet_html = content_match.group(1).strip()
                    print(f"[DEBUG] Successfully loaded Reader mode content, length: {len(tweet_html)}")
                else:
                    # 备用：使用完整的body内容
                    body_match = re.search(r'<body>(.*?)</body>', html_content, re.DOTALL)
                    if body_match:
                        tweet_html = body_match.group(1).strip()
                    else:
                        tweet_html = html_content
                    print(f"[DEBUG] Using fallback HTML content, length: {len(tweet_html)}")
        except Exception as e:
            print(f"[DEBUG] Failed to read HTML file: {e}")
            tweet_html = ""

    # 构造推文数据
    content_type = 'tweet'
    try:
        content_type = task['content_type'] or 'tweet'
    except (IndexError, KeyError):
        pass

    # WeChat articles: render content.md as HTML with local image paths
    if content_type == 'wechat' and not tweet_html:
        content_md_file = os.path.join(actual_save_path, 'content.md')
        if os.path.exists(content_md_file):
            try:
                import re as _re
                import markdown as _md
                md_text = open(content_md_file, encoding='utf-8').read()
                # Replace relative image and video paths with media-serving URLs
                md_text = _re.sub(
                    r'images/(\d+\.\w+)',
                    lambda m: f'/media/{task_id}/images/{m.group(1)}',
                    md_text
                )
                md_text = _re.sub(
                    r'videos/(video\d+\.\w+)',
                    lambda m: f'/media/{task_id}/videos/{m.group(1)}',
                    md_text
                )
                tweet_html = _md.markdown(md_text, extensions=['nl2br', 'tables'])
                # Replace video links with inline <video> players
                tweet_html = _re.sub(
                    r'<a href="(/media/\d+/videos/video\d+\.[^"]+)">视频[^<]*</a>',
                    lambda m: (
                        f'<video controls style="max-width:100%;margin:8px 0">'
                        f'<source src="{m.group(1)}" type="video/mp4"></video>'
                    ),
                    tweet_html
                )
            except Exception as e:
                print(f"[DEBUG] WeChat markdown render failed: {e}")

    # YouTube: render content.md as HTML
    if content_type == 'youtube' and not tweet_html:
        content_md_file = os.path.join(actual_save_path, 'content.md')
        if os.path.exists(content_md_file):
            try:
                import markdown as _md
                md_text = open(content_md_file, encoding='utf-8').read()
                # Keep title + video link, strip other metadata fields
                if '\n---\n' in md_text:
                    header, body = md_text.split('\n---\n', 1)
                    title_line = ''
                    video_link = ''
                    for line in header.splitlines():
                        if line.startswith('# ') and not title_line:
                            title_line = line + '\n\n'
                        elif line.strip().startswith('[视频]'):
                            video_link = line.strip() + '\n\n'
                    md_text = title_line + video_link + body.strip()
                # Rewrite video paths to media-serving URLs
                md_text = re.sub(
                    r'videos/(video\.\w+)',
                    lambda m: f'/media/{task_id}/videos/{m.group(1)}',
                    md_text
                )
                tweet_html = _md.markdown(md_text, extensions=['nl2br', 'tables'])
                # Replace video links with inline <video> players
                tweet_html = re.sub(
                    r'<a href="(/media/\d+/videos/video\.[^"]+)">([^<]*)</a>',
                    lambda m: (
                        f'<video controls style="max-width:100%;margin:8px 0">'
                        f'<source src="{m.group(1)}" type="video/mp4"></video>'
                    ),
                    tweet_html
                )
            except Exception as e:
                print(f"[DEBUG] YouTube markdown render failed: {e}")

    # 兜底检测：DB 中 content_type 可能因以下原因误判为 'tweet'：
    # 1. 通过 /status/ URL 提交的长文（动态检测路径，URL 不含 /article/）
    # 2. 迁移前保存的旧记录（content_type 列为 NULL）
    # 如果 content.html 使用了长文专用模板（标题为 '长文'），则视为长文
    is_article = content_type == 'article'
    if not is_article:
        # 读取 content.html 完整内容，检查是否使用了长文专属模板标题
        try:
            with open(content_html_file, 'r', encoding='utf-8') as _f:
                if '<title>长文</title>' in _f.read():
                    is_article = True
        except Exception:
            pass

    # WeChat/YouTube: content is inline in the rendered HTML — no separate media grid needed
    display_media_files = [] if (content_type in ('wechat', 'youtube') and tweet_html) else media_files

    # Check for transcript
    has_transcript = os.path.exists(os.path.join(actual_save_path, 'transcript.txt'))

    tweet_data = {
        'id': task['tweet_id'],
        'author_name': task['author_name'],
        'author_username': task['author_username'],
        'url': task['url'],
        'is_thread': task['is_thread'],
        'tweet_count': task['tweet_count'],
        'media_count': len(media_files),
        'processed_at': task['processed_at'],
        'media_files': display_media_files,
        'avatar_file': avatar_file,
        'text': tweet_text,
        'html_content': tweet_html,
        'content_type': content_type,
        'is_article': is_article,
        'has_transcript': has_transcript,
        'task_id': task_id,
    }

    return render_template('tweet_display.html', tweet=tweet_data, task_id=task_id)


@app.route('/transcript/<int:task_id>')
def show_transcript(task_id):
    """Serve transcript.txt as a readable HTML page."""
    conn = get_db_connection()
    task = conn.execute('SELECT save_path, author_name, url FROM tasks WHERE id = ?', (task_id,)).fetchone()
    conn.close()
    if not task:
        return 'Not found', 404
    save_path = find_actual_tweet_directory(normalize_path_cross_platform(task['save_path']))
    transcript_path = os.path.join(save_path, 'transcript.txt')
    if not os.path.exists(transcript_path):
        return 'Transcript not available', 404
    text = open(transcript_path, encoding='utf-8').read().strip()
    title = task['author_name'] or 'Transcript'
    html = f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - Transcript</title>
<style>
  body {{font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 760px; margin: 40px auto; padding: 0 20px;
         line-height: 1.8; color: #222; background: #fafafa;}}
  h1 {{font-size: 1.2rem; color: #555; margin-bottom: 4px;}}
  .meta {{font-size: 0.85rem; color: #888; margin-bottom: 24px;}}
  .meta a {{color: #1a73e8; text-decoration: none;}}
  pre {{white-space: pre-wrap; word-break: break-word; font-family: inherit;
        font-size: 1rem; margin: 0;}}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta"><a href="{task['url']}" target="_blank">{task['url']}</a></div>
<pre>{text}</pre>
</body>
</html>'''
    return html

@app.route('/delete/<int:task_id>', methods=['POST'])
@login_required
def delete_tweet(task_id):
    """删除已保存的推文"""
    try:
        conn = get_db_connection()
        task = conn.execute(
            'SELECT * FROM tasks WHERE id = ?',
            (task_id,)
        ).fetchone()
        
        if not task:
            conn.close()
            return jsonify({'success': False, 'message': 'Task not found'})
        
        # 删除文件夹
        save_path = task['save_path']
        if save_path:
            # 使用通用函数标准化路径
            normalized_save_path = normalize_path_cross_platform(save_path)
            # 查找实际存在的目录
            actual_save_path = find_actual_tweet_directory(normalized_save_path)
            
            if os.path.exists(actual_save_path):
                import shutil
                shutil.rmtree(actual_save_path)
        
        # 从数据库中删除记录
        conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Task deleted'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Delete failed: {str(e)}'})

@app.route('/debug')
@login_required
def debug():
    """调试页面"""
    return render_template('debug.html')

@app.route('/script')
@app.route('/help')  # backward compat redirect
@login_required
def help_page():
    """Tampermonkey script page"""
    return render_template('help.html')

@app.route('/tampermonkey/twitter-saver.user.js')
def serve_userscript():
    """Serve the Tampermonkey userscript file directly."""
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), 'tampermonkey'),
        'twitter-saver.user.js',
        mimetype='application/javascript'
    )

@app.route('/reset_stuck_tasks')
def reset_stuck_tasks():
    """重置卡住的任务"""
    try:
        conn = get_db_connection()
        
        # 获取所有processing任务
        stuck_tasks = conn.execute(
            'SELECT id, url FROM tasks WHERE status = "processing"'
        ).fetchall()
        
        if stuck_tasks:
            print(f"[Reset] Found {len(stuck_tasks)} stuck tasks")
            # 重置为pending
            conn.execute('UPDATE tasks SET status = "pending" WHERE status = "processing"')
            conn.commit()
            
            # 重新加入队列
            for task in stuck_tasks:
                enqueue_task(task['id'], task['url'])
                print(f"[Reset] Requeued task {task['id']}")
            
            message = f"Reset {len(stuck_tasks)} stuck tasks and requeued them"
        else:
            message = "No stuck tasks found"
        
        conn.close()
        
        return jsonify({
            'success': True,
            'message': message,
            'queue_size': processing_queue.qsize()
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@app.route('/force_start_queue')
def force_start_queue():
    """强制启动队列处理器"""
    global processing_thread
    
    try:
        print("[Force Start] Force starting queue processor...")
        
        # 检查线程状态
        thread_alive = processing_thread.is_alive() if processing_thread else False
        print(f"[Force Start] Thread alive: {thread_alive}")
        
        # 强制重置所有processing任务为pending
        conn = get_db_connection()
        processing_tasks = conn.execute(
            'SELECT id FROM tasks WHERE status = "processing"'
        ).fetchall()
        
        if processing_tasks:
            print(f"[Force Start] Resetting {len(processing_tasks)} processing tasks to pending...")
            conn.execute('UPDATE tasks SET status = "pending" WHERE status = "processing"')
            conn.commit()
        
        conn.close()
        
        # 重新启动线程（如果需要）
        if not thread_alive:
            print("[Force Start] Starting queue processor thread...")
            start_background_thread()
            
        # 重新加载待处理任务
        print("[Force Start] Reloading pending tasks...")
        load_pending_tasks()
        
        queue_size = processing_queue.qsize()
        print(f"[Force Start] Queue size after reload: {queue_size}")
        
        return jsonify({
            'success': True,
            'message': f'Queue processor restarted. Thread alive: {processing_thread.is_alive() if processing_thread else False}, Queue size: {queue_size}',
            'queue_size': queue_size
        })
    except Exception as e:
        print(f"[Force Start] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })

# 全局变量用于跟踪当前处理状态
current_task_status = {
    'task_id': None,
    'status': 'idle',
    'progress': '',
    'start_time': None,
    'last_update': None,
    'retry_time': None,
    'error_message': None
}

def update_task_progress(task_id, status, progress='', error_message=None, retry_time=None):
    """更新任务处理进度"""
    global current_task_status
    current_task_status.update({
        'task_id': task_id,
        'status': status,
        'progress': progress,
        'last_update': get_current_time().strftime('%H:%M:%S'),
        'error_message': error_message,
        'retry_time': retry_time
    })
    if status == 'started':
        current_task_status['start_time'] = get_current_time().strftime('%H:%M:%S')

@app.route('/api/fts/rebuild', methods=['POST'])
@login_required
def api_fts_rebuild():
    """Rebuild the FTS5 full-text search index from all completed tasks."""
    count = rebuild_fts_index()
    return jsonify({'success': True, 'message': f'Rebuilt FTS index: {count} entries indexed.'})


@app.route('/api/debug')
def api_debug():
    """获取详细的调试信息"""
    conn = get_db_connection()
    
    # 获取所有任务的详细信息
    all_tasks = conn.execute('''
        SELECT * FROM tasks 
        ORDER BY created_at DESC 
        LIMIT 10
    ''').fetchall()
    
    tasks_info = []
    for task in all_tasks:
        task_dict = dict(task)
        if task_dict['created_at']:
            created_time = parse_time_from_db(task_dict['created_at'])
            task_dict['created_at'] = created_time.strftime('%Y-%m-%d %H:%M:%S') if created_time else task_dict['created_at']
        if task_dict['processed_at']:
            processed_time = parse_time_from_db(task_dict['processed_at'])
            task_dict['processed_at'] = processed_time.strftime('%Y-%m-%d %H:%M:%S') if processed_time else task_dict['processed_at']
        tasks_info.append(task_dict)
    
    conn.close()
    
    # 检查 Docker 容器状态
    def check_docker_container(name):
        try:
            result = subprocess.run(
                ['docker', 'inspect', name, '--format', '{{.State.Running}}'],
                capture_output=True, text=True, timeout=3
            )
            return result.returncode == 0 and result.stdout.strip() == 'true'
        except Exception:
            return False

    # 检查服务状态
    services_status = {
        'config_manager': config_manager is not None,
        'twitter_service': twitter_service is not None,
        'media_downloader': media_downloader is not None,
        'file_manager': file_manager is not None,
        'processing_thread_alive': processing_thread.is_alive() if processing_thread else False,
        'processing_thread_exists': processing_thread is not None,
        'xhs_mcp_docker': check_docker_container('xiaohongshu-mcp')
    }
    
    # 获取配置信息
    config_info = {}
    if config_manager:
        try:
            config = config_manager.load_config()
            config_info = {
                'scraping_mode': 'Web Scraping (Playwright)',
                'save_path': config.get('save_path'),
                'max_retries': config.get('max_retries'),
                'timeout_seconds': config.get('timeout_seconds'),
                'create_date_folders': config.get('create_date_folders'),
                'use_playwright': config.get('use_playwright'),
                'playwright_headless': config.get('playwright_headless')
            }
        except Exception as e:
            config_info = {'error': str(e)}
    
    with _queued_task_ids_lock:
        queued_ids_snapshot = list(_queued_task_ids)

    return jsonify({
        'queue_size': processing_queue.qsize(),
        'queued_task_ids': queued_ids_snapshot,
        'queued_task_ids_count': len(queued_ids_snapshot),
        'is_processing': is_processing,
        'services_status': services_status,
        'config_info': config_info,
        'recent_tasks': tasks_info,
        'current_time': get_current_time().strftime('%Y-%m-%d %H:%M:%S'),
        'current_task_status': current_task_status
    })

@app.route('/media/<int:task_id>/preview')
def serve_media_preview(task_id):
    """提供媒体预览图（返回第一个媒体文件）"""
    conn = get_db_connection()
    task = conn.execute(
        'SELECT save_path FROM tasks WHERE id = ? AND status = "completed"',
        (task_id,)
    ).fetchone()
    conn.close()
    
    if not task:
        return "Task not found", 404
    
    save_path = task['save_path']
    # 使用通用函数标准化路径
    normalized_save_path = normalize_path_cross_platform(save_path)
    # 查找实际存在的目录
    actual_save_path = find_actual_tweet_directory(normalized_save_path)
    
    # 查找第一个媒体文件
    # 优先顺序：1) 视频缩略图 2) images目录中的第一个图片 3) videos目录中的第一个视频
    
    # 1. 优先检查视频缩略图
    thumbnails_dir = os.path.join(actual_save_path, 'thumbnails')
    if os.path.exists(thumbnails_dir):
        thumbnail_files = []
        for filename in os.listdir(thumbnails_dir):
            if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                thumbnail_files.append(filename)
        
        if thumbnail_files:
            # 返回第一个缩略图
            first_thumbnail = sorted(thumbnail_files)[0]
            return send_from_directory(thumbnails_dir, first_thumbnail)
    
    # 2. 检查images目录中的图片
    images_dir = os.path.join(actual_save_path, 'images')
    if os.path.exists(images_dir):
        image_files = []
        for filename in os.listdir(images_dir):
            if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                image_files.append(filename)
        
        if image_files:
            # 返回第一个图片
            first_image = sorted(image_files)[0]
            return send_from_directory(images_dir, first_image)
    
    # 3. 如果没有图片和缩略图，返回视频本身（虽然浏览器可能无法预览）
    videos_dir = os.path.join(actual_save_path, 'videos')
    if os.path.exists(videos_dir):
        video_files = []
        for filename in os.listdir(videos_dir):
            if filename.lower().endswith(('.mp4', '.mov', '.avi', '.webm')):
                video_files.append(filename)
        
        if video_files:
            # 返回第一个视频文件
            first_video = sorted(video_files)[0]
            return send_from_directory(videos_dir, first_video)
    
    return "No media files", 404

@app.route('/media/<int:task_id>/<path:filename>')
def serve_media(task_id, filename):
    """提供媒体文件"""
    conn = get_db_connection()
    task = conn.execute(
        'SELECT save_path FROM tasks WHERE id = ? AND status = "completed"',
        (task_id,)
    ).fetchone()
    conn.close()
    
    if not task:
        return "Task not found", 404
    
    save_path = task['save_path']
    # 使用通用函数标准化路径
    normalized_save_path = normalize_path_cross_platform(save_path)
    # 查找实际存在的目录
    actual_save_path = find_actual_tweet_directory(normalized_save_path)
    
    
    # 检查是否为头像文件
    if filename == 'avatar.jpg':
        avatar_path = os.path.join(actual_save_path, 'avatar.jpg')
        if os.path.exists(avatar_path):
            return send_from_directory(actual_save_path, 'avatar.jpg')
    
    # 处理子目录中的文件
    if '/' in filename:
        parts = filename.split('/', 1)
        if len(parts) == 2:
            subdir, actual_filename = parts
            if subdir in ['images', 'videos', 'thumbnails']:
                # Security: reject path traversal; preserve unicode filenames
                if '..' not in actual_filename and not actual_filename.startswith('/'):
                    media_dir = os.path.join(actual_save_path, subdir)
                    full_path = os.path.join(media_dir, actual_filename)
                    if os.path.exists(full_path):
                        return send_from_directory(media_dir, actual_filename)

    # 安全检查文件名（用于向后兼容，仅 ASCII 文件名）
    safe_name = secure_filename(filename)
    if safe_name:
        for subdir in ['images', 'videos', 'thumbnails']:
            media_dir = os.path.join(actual_save_path, subdir)
            if os.path.exists(os.path.join(media_dir, safe_name)):
                return send_from_directory(media_dir, safe_name)

    return "File not found", 404

def task_monitor():
    """任务监控器，定期检查卡住的任务"""
    print("[Task Monitor] Starting task monitor thread...")
    
    while True:
        try:
            time.sleep(300)  # 每5分钟检查一次
            
            conn = get_db_connection()
            
            # 查找处理时间超过10分钟的processing任务
            stuck_tasks = conn.execute('''
                SELECT id, url, processed_at 
                FROM tasks 
                WHERE status = "processing" 
                AND datetime(processed_at) < datetime('now', '-10 minutes')
            ''').fetchall()
            
            if stuck_tasks:
                print(f"[Task Monitor] Found {len(stuck_tasks)} stuck tasks, recovering...")
                
                for task in stuck_tasks:
                    print(f"[Task Monitor] Recovering stuck task {task['id']}")
                    # 重置为pending状态
                    conn.execute(
                        'UPDATE tasks SET status = ?, error_message = ? WHERE id = ?',
                        ('pending', 'Task recovered from stuck state', task['id'])
                    )
                    # 重新加入队列
                    enqueue_task(task['id'], task['url'])
                
                conn.commit()
                print(f"[Task Monitor] Recovered {len(stuck_tasks)} stuck tasks")
            
            conn.close()
            
        except Exception as e:
            print(f"[Task Monitor] Error in task monitor: {e}")

def start_background_thread():
    """启动后台处理线程"""
    global processing_thread
    if processing_thread is None or not processing_thread.is_alive():
        info("[Main] Starting background processing thread...")
        processing_thread = threading.Thread(target=queue_processor, daemon=True)
        processing_thread.start()
        success(f"[Main] Background thread started: {processing_thread.is_alive()}")
        
        # 启动任务监控线程
        monitor_thread = threading.Thread(target=task_monitor, daemon=True)
        monitor_thread.start()
        success("[Main] Task monitor thread started")

# Flask应用启动时的钩子
@app.before_request
def initialize_app():
    """应用请求前的初始化"""
    if not hasattr(app, '_services_initialized'):
        print("[Flask] First request - initializing services in Flask context...")
        print(f"[Flask] Global variables before init: config_manager={config_manager}, twitter_service={twitter_service}")
        
        result = init_services()
        print(f"[Flask] init_services() returned: {result}")
        print(f"[Flask] Global variables after init: config_manager={config_manager}, twitter_service={twitter_service}")
        
        if not result:
            print("[Flask] Failed to initialize services in Flask context!")
        else:
            print("[Flask] Services initialized successfully in Flask context")
        app._services_initialized = True
    
    if not hasattr(app, '_background_thread_started'):
        print("[Flask] First request - initializing background thread...")
        start_background_thread()
        # 自动检测并修复卡住的任务
        auto_fix_stuck_tasks()
        app._background_thread_started = True

def auto_fix_stuck_tasks():
    """自动修复卡住的任务"""
    try:
        conn = get_db_connection()
        
        # 检查是否有卡住的processing任务
        stuck_tasks = conn.execute(
            'SELECT id, url FROM tasks WHERE status = "processing"'
        ).fetchall()
        
        if stuck_tasks:
            print(f"[Auto Fix] Found {len(stuck_tasks)} stuck tasks, auto-fixing...")
            
            # 重置为pending
            conn.execute('UPDATE tasks SET status = "pending" WHERE status = "processing"')
            conn.commit()
            
            # 重新加入队列
            for task in stuck_tasks:
                enqueue_task(task['id'], task['url'])
                print(f"[Auto Fix] Requeued task {task['id']}")
            
            print(f"[Auto Fix] Auto-fixed {len(stuck_tasks)} stuck tasks")

        conn.close()

    except Exception as e:
        print(f"[Auto Fix] Error in auto fix: {e}")

def load_pending_tasks():
    """加载数据库中的待处理任务到队列"""
    conn = get_db_connection()
    
    # 首先，将所有processing状态的任务重置为pending（可能是之前异常退出导致的）
    processing_tasks = conn.execute(
        'SELECT id FROM tasks WHERE status = "processing"'
    ).fetchall()
    
    if processing_tasks:
        print(f"[Startup] Found {len(processing_tasks)} stuck processing tasks, resetting to pending...")
        conn.execute('UPDATE tasks SET status = "pending" WHERE status = "processing"')
        conn.commit()
        print(f"[Startup] Reset {len(processing_tasks)} stuck tasks to pending")
    
    # 加载所有pending任务到队列
    pending_tasks = conn.execute(
        'SELECT id, url FROM tasks WHERE status = "pending" ORDER BY created_at ASC'
    ).fetchall()
    
    for task in pending_tasks:
        if enqueue_task(task['id'], task['url']):
            print(f"[Startup] Loaded pending task {task['id']} into queue")
    
    conn.close()
    
    if pending_tasks:
        print(f"[Startup] Loaded {len(pending_tasks)} pending tasks into queue")
    else:
        print("[Startup] No pending tasks found")

@app.route('/api/retry-tasks')
def api_retry_tasks():
    """获取重试任务列表API"""
    conn = get_db_connection()
    
    # 查询所有有重试记录的任务
    query = """
        SELECT id, url, status, retry_count, max_retries, next_retry_time, 
               error_message, created_at, processed_at, author_username, tweet_id
        FROM tasks 
        WHERE retry_count > 0 
        ORDER BY next_retry_time ASC, created_at DESC
    """
    
    tasks = conn.execute(query).fetchall()
    conn.close()
    
    # 转换为字典列表并添加状态信息
    retry_list = []
    for task in tasks:
        task_dict = dict(task)
        
        # 计算重试状态
        if task_dict['next_retry_time']:
            next_retry = parse_time_from_db(task_dict['next_retry_time'])
            now = get_current_time()
            
            if task_dict['status'] == 'pending' and next_retry <= now:
                task_dict['retry_status'] = 'ready'
                task_dict['retry_status_text'] = 'Ready to retry'
            elif task_dict['status'] == 'pending':
                remaining = next_retry - now
                minutes = int(remaining.total_seconds() / 60)
                task_dict['retry_status'] = 'waiting'
                task_dict['retry_status_text'] = f'Retry in {minutes}m'
            else:
                task_dict['retry_status'] = task_dict['status']
                task_dict['retry_status_text'] = task_dict['status']
        else:
            task_dict['retry_status'] = task_dict['status']
            task_dict['retry_status_text'] = task_dict['status']
        
        # 格式化时间
        if task_dict['created_at']:
            created_time = parse_time_from_db(task_dict['created_at'])
            task_dict['created_at'] = created_time.strftime('%Y-%m-%d %H:%M:%S') if created_time else task_dict['created_at']
        if task_dict['next_retry_time']:
            retry_time = parse_time_from_db(task_dict['next_retry_time'])
            task_dict['next_retry_time'] = retry_time.strftime('%Y-%m-%d %H:%M:%S') if retry_time else task_dict['next_retry_time']
        
        retry_list.append(task_dict)
    
    return jsonify({
        'retry_tasks': retry_list,
        'total': len(retry_list)
    })

@app.route('/api/retry-now/<int:task_id>', methods=['POST'])
def api_retry_now(task_id):
    """立即重试指定任务"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 检查任务是否存在且可以重试
        task = cursor.execute(
            'SELECT id, url, retry_count, max_retries, status FROM tasks WHERE id = ?',
            (task_id,)
        ).fetchone()
        
        if not task:
            return jsonify({'success': False, 'message': 'Task not found'})
        
        if task['status'] not in ['pending', 'failed']:
            return jsonify({'success': False, 'message': 'Task status does not allow retry'})
        
        retry_count = task['retry_count'] if task['retry_count'] else 0
        max_retries = task['max_retries'] if task['max_retries'] else 3
        
        if retry_count >= max_retries:
            return jsonify({'success': False, 'message': 'Maximum retry count reached'})
        
        # 清除重试时间并设置为pending
        cursor.execute("""
            UPDATE tasks SET 
                status = 'pending',
                next_retry_time = NULL,
                error_message = ?
            WHERE id = ?
        """, (f'Manual retry {retry_count + 1}/{max_retries}', task_id))
        
        # 添加到处理队列
        enqueue_task(task_id, task['url'])
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Task added to retry queue'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Retry failed: {str(e)}'})

@app.route('/api/reset-retries/<int:task_id>', methods=['POST'])
def api_reset_retries(task_id):
    """重置任务的重试计数"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 首先获取任务URL
        task = cursor.execute(
            'SELECT url FROM tasks WHERE id = ?', (task_id,)
        ).fetchone()
        
        if not task:
            return jsonify({'success': False, 'message': 'Task not found'})
        
        task_url = task['url']
        
        # 重置重试相关字段
        cursor.execute("""
            UPDATE tasks SET 
                retry_count = 0,
                next_retry_time = NULL,
                status = 'pending',
                error_message = 'Retry count reset, ready for new attempt'
            WHERE id = ?
        """, (task_id,))
        
        conn.commit()
        conn.close()
        
        # 将任务加入处理队列
        enqueue_task(task_id, task_url)
        info(f"[Reset Retries] Task {task_id} reset and added to queue: {task_url}")
        
        return jsonify({'success': True, 'message': 'Retry count reset, task requeued'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Reset failed: {str(e)}'})

@app.route('/api/delete-retry-task/<int:task_id>', methods=['POST'])
def api_delete_retry_task(task_id):
    """删除重试任务"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 首先获取任务信息
        task = cursor.execute(
            'SELECT url, status, retry_count FROM tasks WHERE id = ?', (task_id,)
        ).fetchone()
        
        if not task:
            return jsonify({'success': False, 'message': 'Task not found'})
        
        task_url = task['url']
        task_status = task['status']
        retry_count = task['retry_count']
        
        # 删除任务记录
        cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        
        conn.commit()
        conn.close()
        
        info(f"[Delete Retry Task] Task {task_id} deleted: {task_url} (status: {task_status}, retries: {retry_count})")
        
        return jsonify({'success': True, 'message': 'Retry task deleted'})
        
    except Exception as e:
        error(f"[Delete Retry Task] Failed to delete task {task_id}: {str(e)}")
        return jsonify({'success': False, 'message': f'Delete failed: {str(e)}'})

@app.route('/api/submit', methods=['POST'])
def api_submit():
    """API方式提交推文URL进行下载
    
    支持的请求格式:
    1. JSON: {"url": "https://twitter.com/user/status/123456"}
    2. Form: url=https://twitter.com/user/status/123456
    3. Text: 直接在body中放置URL
    """
    try:
        # 尝试多种方式获取URL
        url = None
        
        # 方式1: JSON格式
        if request.is_json:
            data = request.get_json()
            url = data.get('url') if data else None
        
        # 方式2: Form格式
        if not url and request.form:
            url = request.form.get('url')
        
        # 方式3: 纯文本格式
        if not url and request.data:
            text_data = request.data.decode('utf-8').strip()
            # 检查是否是有效的Twitter URL
            if TwitterURLParser.is_valid_twitter_url(text_data):
                url = text_data
        
        # 方式4: URL参数
        if not url:
            url = request.args.get('url')
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL is required',
                'message': 'Please provide a Twitter URL',
                'supported_formats': [
                    'JSON: {"url": "https://twitter.com/user/status/123456"}',
                    'Form: url=https://twitter.com/user/status/123456',
                    'Text: place URL directly in body',
                    'Query: ?url=https://twitter.com/user/status/123456'
                ]
            }), 400
        
        # 验证URL格式
        if not TwitterURLParser.is_valid_twitter_url(url):
            return jsonify({
                'success': False,
                'error': 'Invalid Twitter URL',
                'message': f'Invalid Twitter URL: {url}',
                'url': url
            }), 400
        
        # 检查URL是否已存在
        conn = get_db_connection()
        existing_task = conn.execute(
            'SELECT id, status FROM tasks WHERE url = ?', (url,)
        ).fetchone()
        
        if existing_task:
            task_id = existing_task['id']
            status = existing_task['status']
            conn.close()
            
            return jsonify({
                'success': True,
                'message': f'Task already exists (status: {status})',
                'task_id': task_id,
                'url': url,
                'status': status,
                'duplicate': True
            }), 200
        
        # 创建新任务
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO tasks (url, status, created_at) VALUES (?, ?, ?)',
            (url, 'pending', format_time_for_db(get_current_time()))
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # 添加到处理队列
        enqueue_task(task_id, url)
        info(f"[API Submit] Added task {task_id} to queue. Queue size: {processing_queue.qsize()}")
        
        return jsonify({
            'success': True,
            'message': 'Task added to queue',
            'task_id': task_id,
            'url': url,
            'status': 'pending',
            'queue_size': processing_queue.qsize()
        }), 201
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'Internal server error',
            'message': f'Server error: {str(e)}'
        }), 500

def get_xhs_save_path() -> str:
    """Return the XHS base save directory — same as Twitter's save path."""
    if config_manager:
        return config_manager.get_save_path()
    return os.path.join(DATA_DIR, 'saved_tweets')


def make_xhs_service() -> 'XHSService':
    """Instantiate XHSService with the same path/folder settings as Twitter."""
    create_date_folders = config_manager.get_create_date_folders() if config_manager else True
    return XHSService(get_xhs_save_path(), create_date_folders=create_date_folders)


def register_xhs_task(url: str, result: dict) -> tuple[int, str]:
    """Insert a completed XHS save as a task in the DB.

    Returns (task_id, share_slug).
    """
    conn = get_db_connection()
    slug = generate_unique_slug()
    now = format_time_for_db(get_current_time())
    conn.execute(
        '''INSERT INTO tasks
               (url, status, processed_at, tweet_id, author_username, author_name,
                save_path, tweet_text, content_type, share_slug,
                is_thread, tweet_count, media_count)
           VALUES (?, 'completed', ?, ?, ?, ?, ?, ?, 'xhs', ?, 0, 1, ?)''',
        (url, now,
         result['feed_id'],
         result.get('author_username', ''),
         result.get('author_name', ''),
         result['save_path'],
         result.get('tweet_text', ''),
         slug,
         result.get('media_count', result.get('image_count', 0)))
    )
    conn.commit()
    task_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return task_id, slug


# ---------------------------------------------------------------------------
# App settings helpers
# ---------------------------------------------------------------------------

def get_setting(key: str, default: str = '') -> str:
    conn = get_db_connection()
    row = conn.execute('SELECT value FROM app_settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else default


def set_setting(key: str, value: str):
    conn = get_db_connection()
    conn.execute('INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# XHS auto-save background job
# ---------------------------------------------------------------------------

_xhs_autosave_thread: threading.Thread = None
_xhs_autosave_stop = threading.Event()


def _xhs_autosave_worker():
    """Background thread: periodically fetch home feed and save new posts."""
    info('[XHS AutoSave] Worker started')
    while not _xhs_autosave_stop.is_set():
        try:
            interval = int(get_setting('xhs_autosave_interval_minutes', '30'))
        except ValueError:
            interval = 30

        # Wait for the configured interval (check stop every 10s)
        for _ in range(interval * 6):
            if _xhs_autosave_stop.is_set():
                return
            time.sleep(10)

        if _xhs_autosave_stop.is_set():
            return

        if get_setting('xhs_autosave_enabled', 'false') != 'true':
            continue

        _run_xhs_autosave()

    info('[XHS AutoSave] Worker stopped')


def _run_xhs_autosave():
    """Fetch 我的收藏, save posts not already in the DB."""
    info('[XHS AutoSave] Running...')
    saved_count = 0
    try:
        user_id = get_setting('xhs_user_id', '').strip()
        xhs = make_xhs_service()
        feeds = xhs.get_favorites(user_id=user_id or None)

        conn = get_db_connection()
        existing_ids = {
            row[0] for row in
            conn.execute("SELECT tweet_id FROM tasks WHERE content_type='xhs'").fetchall()
        }
        conn.close()

        for feed in feeds:
            feed_id = feed['feed_id']
            if feed_id in existing_ids:
                continue
            try:
                result = xhs.save_post(feed['url'])
                register_xhs_task(feed['url'], result)
                existing_ids.add(feed_id)
                saved_count += 1
                info(f'[XHS AutoSave] Saved: {result["title"]}')
            except Exception as e:
                warning(f'[XHS AutoSave] Failed {feed_id}: {e}')

    except Exception as e:
        error(f'[XHS AutoSave] Error: {e}')

    now = format_time_for_db(get_current_time())
    set_setting('xhs_autosave_last_run', now)
    set_setting('xhs_autosave_last_count', str(saved_count))
    info(f'[XHS AutoSave] Done — saved {saved_count} new posts')


def start_xhs_autosave():
    global _xhs_autosave_thread, _xhs_autosave_stop
    _xhs_autosave_stop.clear()
    _xhs_autosave_thread = threading.Thread(
        target=_xhs_autosave_worker, daemon=True, name='xhs-autosave'
    )
    _xhs_autosave_thread.start()


def stop_xhs_autosave():
    _xhs_autosave_stop.set()


# ---------------------------------------------------------------------------
# XHS settings routes
# ---------------------------------------------------------------------------

@app.route('/settings')
@login_required
def settings_page():
    youtube_api_key = config_manager.get_youtube_api_key() if config_manager else ''
    return render_template('settings.html', youtube_api_key=youtube_api_key or '')


@app.route('/api/xhs/settings', methods=['GET'])
@login_required
def api_xhs_settings_get():
    return jsonify({
        'enabled': get_setting('xhs_autosave_enabled', 'false') == 'true',
        'interval_minutes': int(get_setting('xhs_autosave_interval_minutes', '30')),
        'user_id': get_setting('xhs_user_id', ''),
        'last_run': get_setting('xhs_autosave_last_run', ''),
        'last_count': int(get_setting('xhs_autosave_last_count', '0')),
        'thread_alive': _xhs_autosave_thread is not None and _xhs_autosave_thread.is_alive(),
    })


@app.route('/api/xhs/settings', methods=['POST'])
@login_required
def api_xhs_settings_post():
    data = request.get_json() or {}
    if 'enabled' in data:
        enabled = bool(data['enabled'])
        set_setting('xhs_autosave_enabled', 'true' if enabled else 'false')
        if enabled:
            start_xhs_autosave()
        else:
            stop_xhs_autosave()
    if 'interval_minutes' in data:
        try:
            mins = max(5, int(data['interval_minutes']))
        except (ValueError, TypeError):
            mins = 30
        set_setting('xhs_autosave_interval_minutes', str(mins))
    if 'user_id' in data:
        set_setting('xhs_user_id', str(data['user_id']).strip())
    return jsonify({'success': True})


@app.route('/api/settings/youtube-api-key', methods=['POST'])
@login_required
def api_set_youtube_api_key():
    data = request.get_json() or {}
    key = str(data.get('key', '')).strip()
    if config_manager:
        config_manager.set_youtube_api_key(key)
    return jsonify({'success': True})


@app.route('/api/settings/config', methods=['POST'])
@login_required
def api_set_config():
    """Update system configuration (save_path, max_retries, timeout_seconds, create_date_folders, playwright_headless)."""
    if not config_manager:
        return jsonify({'success': False, 'error': 'Config manager not initialized'}), 500
    data = request.get_json() or {}
    try:
        if 'save_path' in data:
            config_manager.set_save_path(str(data['save_path']).strip())
        if 'max_retries' in data:
            config_manager.set_max_retries(int(data['max_retries']))
        if 'timeout_seconds' in data:
            config_manager.set_timeout_seconds(int(data['timeout_seconds']))
        if 'create_date_folders' in data:
            config_manager.set_create_date_folders(bool(data['create_date_folders']))
        if 'playwright_headless' in data:
            config_manager.set_playwright_headless(bool(data['playwright_headless']))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/xhs/run-now', methods=['POST'])
@login_required
def api_xhs_run_now():
    """Trigger an immediate auto-save run in a background thread."""
    t = threading.Thread(target=_run_xhs_autosave, daemon=True, name='xhs-autosave-manual')
    t.start()
    return jsonify({'success': True, 'message': 'Auto-save run started'})


@app.route('/api/xhs/cookie-status')
@login_required
def api_xhs_cookie_status():
    """Check XHS cookie file status."""
    cookies_path = os.path.expanduser('~/.agent-reach/xhs/cookies.json')
    if os.path.exists(cookies_path):
        mtime = os.path.getmtime(cookies_path)
        from datetime import datetime
        modified = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open(cookies_path, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            count = len(cookies) if isinstance(cookies, list) else 0
        except Exception:
            count = 0
        return jsonify({'exists': True, 'modified': modified, 'count': count})
    return jsonify({'exists': False})


@app.route('/api/xhs/cookies', methods=['POST'])
@login_required
def api_xhs_save_cookies():
    """Save XHS cookies from Cookie-Editor JSON export."""
    data = request.get_json()
    if not data or not data.get('cookies'):
        return jsonify({'success': False, 'message': 'No cookie data provided'}), 400

    try:
        cookies = json.loads(data['cookies'])
        if not isinstance(cookies, list):
            return jsonify({'success': False, 'message': 'Expected a JSON array of cookies'}), 400

        cookies_path = os.path.expanduser('~/.agent-reach/xhs/cookies.json')
        os.makedirs(os.path.dirname(cookies_path), exist_ok=True)
        with open(cookies_path, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        return jsonify({'success': True, 'message': f'Saved {len(cookies)} cookies.'})
    except json.JSONDecodeError:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/submit/xhs', methods=['POST'])
def api_submit_xhs():
    """Submit a XiaoHongShu post URL for download.

    Request body (JSON): {"url": "https://www.xiaohongshu.com/explore/...?xsec_token=..."}
    """
    try:
        url = None
        if request.is_json:
            data = request.get_json()
            url = data.get('url') if data else None
        if not url and request.form:
            url = request.form.get('url')
        if not url and request.data:
            url = request.data.decode('utf-8').strip()
        if not url:
            url = request.args.get('url')

        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        # Support mobile app share text (e.g. "caption http://xhslink.com/xxx 复制后打开...")
        url = XHSService.extract_url_from_share_text(url)
        url = XHSService.resolve_xhslink(url)
        url = XHSService.normalize_xhs_url(url)

        if not XHSService.is_valid_xhs_url(url):
            return jsonify({
                'success': False,
                'error': 'Invalid XiaoHongShu URL',
                'message': 'Expected: https://www.xiaohongshu.com/explore/<id>?xsec_token=...',
                'url': url
            }), 400

        # Check duplicate
        conn = get_db_connection()
        existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (url,)).fetchone()
        if existing:
            conn.close()
            return jsonify({
                'success': True, 'duplicate': True,
                'task_id': existing['id'], 'status': existing['status'], 'url': url
            }), 200

        # Insert pending task and enqueue
        cursor = conn.cursor()
        now = format_time_for_db(get_current_time())
        cursor.execute(
            "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, 'xhs')",
            (url, now)
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        enqueue_task(task_id, url)
        info(f'[XHS Submit] Task {task_id} queued. Queue size: {processing_queue.qsize()}')

        return jsonify({
            'success': True,
            'message': 'XHS post added to queue',
            'task_id': task_id,
            'url': url,
            'status': 'pending',
            'queue_size': processing_queue.qsize()
        }), 201

    except XHSServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': 'Internal server error', 'message': str(e)}), 500


# ---------------------------------------------------------------------------
# WeChat helpers and routes
# ---------------------------------------------------------------------------

def make_wechat_service() -> WechatService:
    """Instantiate WechatService with the same path/folder settings as Twitter."""
    create_date_folders = config_manager.get_create_date_folders() if config_manager else True
    base_path = config_manager.get_save_path() if config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    return WechatService(base_path, create_date_folders=create_date_folders)


def register_wechat_task(url: str, result: dict) -> tuple[int, str]:
    """Insert a completed WeChat article save as a task in the DB. Returns (task_id, share_slug)."""
    conn = get_db_connection()
    slug = generate_unique_slug()
    now = format_time_for_db(get_current_time())
    cursor = conn.execute(
        '''INSERT INTO tasks
           (url, status, processed_at, tweet_id, author_username, author_name,
            save_path, tweet_text, content_type, share_slug,
            is_thread, tweet_count, media_count)
           VALUES (?, 'completed', ?, ?, ?, ?, ?, ?, 'wechat', ?, 0, 1, ?)''',
        (
            url,
            now,
            result.get('article_id', ''),
            result.get('author_username', ''),
            result.get('author_name', ''),
            result.get('save_path', ''),
            result.get('tweet_text', '')[:500],
            slug,
            result.get('image_count', 0),
        )
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id, slug


@app.route('/api/submit/wechat', methods=['POST'])
@login_required
def api_submit_wechat():
    """Submit a WeChat 公众号 article URL for archiving.

    Request body (JSON): {"url": "https://mp.weixin.qq.com/s/..."}
    """
    try:
        url = None
        if request.is_json:
            data = request.get_json()
            url = data.get('url') if data else None
        if not url and request.form:
            url = request.form.get('url')
        if not url and request.data:
            url = request.data.decode('utf-8').strip()
        if not url:
            url = request.args.get('url')

        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        if not WechatService.is_valid_wechat_url(url):
            return jsonify({
                'success': False,
                'error': 'Invalid WeChat article URL',
                'message': 'Expected: https://mp.weixin.qq.com/s/...',
                'url': url
            }), 400

        # Check duplicate
        conn = get_db_connection()
        existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (url,)).fetchone()
        if existing:
            conn.close()
            return jsonify({
                'success': True, 'duplicate': True,
                'task_id': existing['id'], 'status': existing['status'], 'url': url
            }), 200

        # Insert pending task and enqueue
        cursor = conn.cursor()
        now = format_time_for_db(get_current_time())
        cursor.execute(
            "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, 'wechat')",
            (url, now)
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        enqueue_task(task_id, url)
        info(f'[WeChat Submit] Task {task_id} queued. Queue size: {processing_queue.qsize()}')

        return jsonify({
            'success': True,
            'message': 'WeChat article added to queue',
            'task_id': task_id,
            'url': url,
            'status': 'pending',
            'queue_size': processing_queue.qsize()
        }), 201

    except WechatServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        error(f'WeChat submit error: {e}')
        return jsonify({'success': False, 'error': 'Internal server error', 'message': str(e)}), 500


# ---------------------------------------------------------------------------
# YouTube helpers and routes
# ---------------------------------------------------------------------------

def make_youtube_service() -> YoutubeService:
    """Instantiate YoutubeService with the same path/folder settings as Twitter."""
    create_date_folders = config_manager.get_create_date_folders() if config_manager else True
    base_path = config_manager.get_save_path() if config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    yt_api_key = config_manager.get_youtube_api_key() if config_manager else None
    return YoutubeService(base_path, create_date_folders=create_date_folders,
                          youtube_api_key=yt_api_key)


@app.route('/api/submit/youtube', methods=['POST'])
@login_required
def api_submit_youtube():
    """Submit a YouTube URL for download.

    Request body (JSON): {"url": "https://www.youtube.com/watch?v=..."}
    """
    try:
        url = None
        if request.is_json:
            data = request.get_json()
            url = data.get('url') if data else None
        if not url and request.form:
            url = request.form.get('url')
        if not url and request.data:
            url = request.data.decode('utf-8').strip()
        if not url:
            url = request.args.get('url')

        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        if not YoutubeService.is_valid_youtube_url(url):
            return jsonify({
                'success': False,
                'error': 'Invalid YouTube URL',
                'message': 'Expected: https://www.youtube.com/watch?v=...',
                'url': url
            }), 400

        url = YoutubeService.normalize_url(url)

        # Check duplicate
        conn = get_db_connection()
        existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (url,)).fetchone()
        if existing:
            conn.close()
            return jsonify({
                'success': True, 'duplicate': True,
                'task_id': existing['id'], 'status': existing['status'], 'url': url
            }), 200

        cursor = conn.cursor()
        now = format_time_for_db(get_current_time())
        cursor.execute(
            "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, 'youtube')",
            (url, now)
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        enqueue_task(task_id, url)
        info(f'[YouTube Submit] Task {task_id} queued. Queue size: {processing_queue.qsize()}')

        return jsonify({
            'success': True,
            'message': 'YouTube video added to queue',
            'task_id': task_id,
            'url': url,
            'status': 'pending',
            'queue_size': processing_queue.qsize()
        }), 201

    except YoutubeServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        error(f'YouTube submit error: {e}')
        return jsonify({'success': False, 'error': 'Internal server error', 'message': str(e)}), 500


@app.route('/api/status/<int:task_id>')
def api_task_status(task_id):
    """获取任务状态"""
    try:
        conn = get_db_connection()
        task = conn.execute(
            'SELECT * FROM tasks WHERE id = ?', (task_id,)
        ).fetchone()
        conn.close()
        
        if not task:
            return jsonify({
                'success': False,
                'error': 'Task not found',
                'message': 'Task not found'
            }), 404
        
        task_data = dict(task)
        
        # 格式化时间
        if task_data['created_at']:
            created_time = parse_time_from_db(task_data['created_at'])
            task_data['created_at'] = created_time.strftime('%Y-%m-%d %H:%M:%S') if created_time else task_data['created_at']
        if task_data['processed_at']:
            processed_time = parse_time_from_db(task_data['processed_at'])
            task_data['processed_at'] = processed_time.strftime('%Y-%m-%d %H:%M:%S') if processed_time else task_data['processed_at']
        if task_data['next_retry_time']:
            retry_time = parse_time_from_db(task_data['next_retry_time'])
            task_data['next_retry_time'] = retry_time.strftime('%Y-%m-%d %H:%M:%S') if retry_time else task_data['next_retry_time']
        
        return jsonify({
            'success': True,
            'task': task_data
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'Internal server error',
            'message': f'Server error: {str(e)}'
        }), 500

@app.route('/api/logs/stream')
def stream_logs():
    """实时日志流 - Server-Sent Events"""
    def generate():
        # 发送已有的日志
        with log_lock:
            for log_entry in log_buffer:
                yield f"data: {log_entry}\n\n"
        
        # 实时推送新日志
        last_count = len(log_buffer)
        while True:
            try:
                with log_lock:
                    current_count = len(log_buffer)
                    if current_count > last_count:
                        # 发送新增的日志
                        new_logs = list(log_buffer)[last_count:]
                        for log_entry in new_logs:
                            yield f"data: {log_entry}\n\n"
                        last_count = current_count
                
                time.sleep(0.5)  # 每0.5秒检查一次新日志
            except GeneratorExit:
                break
            except Exception as e:
                yield f"data: [ERROR] 日志流错误: {str(e)}\n\n"
                break
    
    return Response(generate(), mimetype='text/plain', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Access-Control-Allow-Origin': '*'
    })

@app.route('/api/logs/recent')
def get_recent_logs():
    """获取最近的日志（用于初始化）"""
    with log_lock:
        logs = list(log_buffer)
    return jsonify({
        'success': True,
        'logs': logs
    })

@app.route('/api/logs/test')
def test_logs():
    """测试日志捕获系统"""
    from utils.realtime_logger import info, error, warning, success
    
    info("[TEST] This is a test log message from /api/logs/test endpoint")
    error("[TEST] Testing log capture system - ERROR test")
    warning("[TEST] Warning message test")
    info("[TEST] Multiple line test")
    info("[TEST] 中文测试日志")
    success("[TEST] Test completed successfully")
    
    with log_lock:
        buffer_size = len(log_buffer)
        latest_logs = list(log_buffer)[-5:] if log_buffer else []
    
    return jsonify({
        'success': True,
        'message': 'Test logs generated',
        'buffer_size': buffer_size,
        'latest_logs': latest_logs
    })


# ---------------------------------------------------------------------------
# Telegram bot integration
# ---------------------------------------------------------------------------

def _telegram_submit(url: str) -> dict:
    """Submit a URL from the Telegram bot. Thread-safe — opens its own DB connection."""
    if not TwitterURLParser.is_valid_twitter_url(url):
        return {'success': False, 'error': 'invalid_url'}

    conn = get_db_connection()
    existing = conn.execute(
        'SELECT id, status FROM tasks WHERE url = ?', (url,)
    ).fetchone()
    if existing:
        conn.close()
        return {
            'success': True,
            'duplicate': True,
            'task_id': existing['id'],
            'status': existing['status'],
        }

    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO tasks (url, status, created_at) VALUES (?, ?, ?)',
        (url, 'pending', format_time_for_db(get_current_time()))
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    enqueue_task(task_id, url)
    return {'success': True, 'duplicate': False, 'task_id': task_id}


@app.route('/telegram')
@login_required
def telegram_page():
    """Telegram bot configuration page."""
    return render_template('telegram.html')


@app.route('/api/telegram/status')
@login_required
def telegram_status():
    """Return current bot status, owner info, and whether a token is configured."""
    import configparser as cp
    from services.telegram_bot import get_status
    cfg = cp.ConfigParser()
    if os.path.exists('config.ini'):
        cfg.read('config.ini')
    token_configured = bool(cfg.get('telegram', 'bot_token', fallback='').strip())
    status = get_status()
    status['token_configured'] = token_configured
    return jsonify(status)


@app.route('/api/telegram/config', methods=['POST'])
@login_required
def telegram_config():
    """Save bot token to config.ini and (re)start the bot."""
    import configparser as cp
    from services.telegram_bot import start_bot
    data = request.get_json() or {}
    token = data.get('token', '').strip()
    if not token:
        return jsonify({'success': False, 'error': 'Token is required'}), 400

    cfg = cp.ConfigParser()
    if os.path.exists('config.ini'):
        cfg.read('config.ini')
    if 'telegram' not in cfg:
        cfg['telegram'] = {}
    cfg['telegram']['bot_token'] = token
    with open('config.ini', 'w') as f:
        cfg.write(f)

    start_bot(token, _telegram_submit)
    return jsonify({'success': True, 'message': 'Token saved and bot started'})


@app.route('/api/telegram/reset-owner', methods=['POST'])
@login_required
def telegram_reset_owner():
    """Clear the registered owner so the next /start registers a new one."""
    from services.telegram_bot import clear_owner
    clear_owner()
    return jsonify({'success': True, 'message': 'Owner reset'})


if __name__ == '__main__':
    # 初始化数据库
    init_db()

    # Build FTS index if empty (first run or after DB reset)
    try:
        _fts_conn = get_db_connection()
        _fts_count = _fts_conn.execute("SELECT COUNT(*) FROM tasks_fts").fetchone()[0]
        _tasks_count = _fts_conn.execute("SELECT COUNT(*) FROM tasks WHERE status='completed'").fetchone()[0]
        _fts_conn.close()
        if _fts_count == 0 and _tasks_count > 0:
            print(f"[FTS] Index empty, rebuilding from {_tasks_count} completed tasks...")
            n = rebuild_fts_index()
            print(f"[FTS] Indexed {n} entries.")
    except Exception as e:
        print(f"[FTS] Warning: could not check/rebuild index: {e}")

    # 初始化服务
    if not init_services():
        print("Failed to initialize services. Please check your configuration.")
        exit(1)
    
    # 启动队列处理线程
    start_background_thread()
    
    # 加载待处理任务
    load_pending_tasks()
    
    print("Twitter Saver Web App starting...")
    print("Access the application at: http://localhost:6201")

    app.run(debug=False, host='0.0.0.0', port=6201)
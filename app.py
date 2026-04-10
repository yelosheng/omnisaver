#!/usr/bin/env python3
"""
Twitter内容保存工具 - Web界面
Flask + Bootstrap Web应用
"""

import os
import re
import json
import subprocess
import threading
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory, Response, session, flash
from werkzeug.utils import secure_filename
from services.config_manager import ConfigManager
from services.twitter_service import TwitterService, TwitterScrapingError
from services.media_downloader import MediaDownloader
from services.file_manager import FileManager
from services.user_manager import UserManager
from services.xhs_service import XHSService, XHSServiceError
from services.wechat_service import WechatService, WechatServiceError
from services.youtube_service import YoutubeService, YoutubeServiceError
from services.douyin_service import DouyinService, DouyinServiceError
from services.weibo_service import WeiboService, WeiboServiceError
from services.bilibili_service import BilibiliService, BilibiliServiceError
from services.kuaishou_service import KuaishouService, KuaishouServiceError
from services.instagram_service import InstagramService, InstagramServiceError
from services.zhihu_service import ZhihuService, ZhihuServiceError
from services.pinterest_service import PinterestService, PinterestServiceError
from services.reddit_service import RedditService, RedditServiceError
from services.feishu_service import FeishuService
from services.webpage_service import WebpageService, WebpageServiceError
from utils.url_parser import TwitterURLParser
import glob as _glob

# ── i18n ──────────────────────────────────────────────────────────────────────
_TRANSLATIONS: dict = {}

def _load_translations():
    translations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'translations')
    for path in _glob.glob(os.path.join(translations_dir, '*.json')):
        lang = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding='utf-8') as f:
            _TRANSLATIONS[lang] = json.load(f)

_load_translations()
_SUPPORTED_LANGS = list(_TRANSLATIONS.keys())  # ['en', 'zh_CN']
# ──────────────────────────────────────────────────────────────────────────────

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
from utils.realtime_logger import (
    log_buffer, log_lock, log, info, error, warning, success, debug,
    get_formatted_logs, get_logs_after, get_latest_seq, format_log_entry,
)
from services.db import (
    normalize_path_cross_platform, find_actual_tweet_directory,
    get_current_time, format_time_for_db, parse_time_from_db,
    generate_unique_slug, init_db, fts_upsert, _read_full_text,
    _read_title, rebuild_fts_index, get_db_connection,
    get_setting, set_setting,
)
from services.background import (
    processing_queue, is_processing, _queued_task_ids,
    _queued_task_ids_lock, processing_thread, current_task_status,
    _xhs_autosave_stop, enqueue_task, start_background_thread,
    load_pending_tasks, start_xhs_autosave, stop_xhs_autosave,
    auto_fix_stuck_tasks, update_task_progress,
    register_xhs_task, register_wechat_task, init_background,
    _xhs_autosave_thread, _run_xhs_autosave,
)

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
    """注入用户登录状态和 i18n 翻译到所有模板"""
    lang = session.get('lang', 'en')
    if lang not in _TRANSLATIONS:
        lang = 'en'
    return {
        'is_logged_in': session.get('logged_in', False),
        'username': session.get('username', None),
        't': _TRANSLATIONS.get(lang, _TRANSLATIONS.get('en', {})),
        'current_lang': lang,
    }

# 全局变量
config_manager = None
twitter_service = None
media_downloader = None
file_manager = None
user_manager = UserManager(os.path.join(DATA_DIR, 'users.json'))  # Initialize UserManager

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


def check_api_key(provided_key: str) -> bool:
    """Return True if the request is authorized.

    Authorization logic:
    - If no api_key is configured in app_settings, always allow (backward compat).
    - Otherwise, provided_key must match exactly.
    """
    configured = get_setting('api_key', '')
    if not configured:
        return True
    return provided_key == configured



def init_services():
    """初始化服务"""
    global config_manager, twitter_service, media_downloader, file_manager
    
    try:
        info("[Init] Starting service initialization")
        info(f"[Init] Current globals: config_manager={config_manager is not None}, twitter_service={twitter_service is not None}")

        info("[Init] Creating ConfigManager")
        config_manager = ConfigManager()
        info("[Init] ConfigManager created")

        info("[Init] Validating config")
        if not config_manager.validate_config():
            error("[Init] Config validation failed")
            return False
        success("[Init] Config validation passed")

        info("[Init] Loading config")
        config = config_manager.load_config()
        success("[Init] Config loaded successfully")

        info("[Init] Creating TwitterService")
        twitter_service = TwitterService(
            max_retries=config['max_retries'],
            timeout=config['timeout_seconds'],
            use_playwright=config.get('use_playwright', True),
            xreach_auth_token=config_manager.get_twitter_auth_token(),
            xreach_ct0=config_manager.get_twitter_ct0()
        )
        info("[Init] TwitterService created")

        info("[Init] Creating MediaDownloader")
        media_downloader = MediaDownloader(
            max_retries=config['max_retries'],
            timeout=config['timeout_seconds'],
            twitter_auth_token=config_manager.get_twitter_auth_token(),
            twitter_ct0=config_manager.get_twitter_ct0()
        )
        info("[Init] MediaDownloader created")

        info("[Init] Creating FileManager")
        file_manager = FileManager(
            base_path=config['save_path'],
            create_date_folders=config['create_date_folders']
        )
        info("[Init] FileManager created")

        success("[Init] All services created successfully")
        init_background(config_manager, twitter_service, media_downloader, file_manager)
        return True
    except Exception as e:
        error(f"[Init] Failed to initialize services: {e}")
        import traceback
        traceback.print_exc()
        return False

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面和处理"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember_days = int(request.form.get('remember_days') or 1)

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

@app.route('/api/set-language')
def set_language():
    from urllib.parse import urlparse, urljoin
    def _is_safe_url(target):
        ref = urlparse(request.host_url)
        test = urlparse(urljoin(request.host_url, target))
        return test.scheme in ('http', 'https') and ref.netloc == test.netloc
    lang = request.args.get('lang', 'en')
    if lang in _SUPPORTED_LANGS:
        session['lang'] = lang
    next_url = request.args.get('next') or request.referrer or '/'
    if not _is_safe_url(next_url):
        next_url = '/'
    return redirect(next_url)

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
    
    # Try Douyin share text extraction first (mobile app shares a text blob with embedded URL)
    douyin_extracted = DouyinService.extract_url_from_share_text(url)
    weibo_extracted = WeiboService.extract_url_from_share_text(url)
    bilibili_extracted = BilibiliService.extract_url_from_share_text(url)
    kuaishou_extracted = KuaishouService.extract_url_from_share_text(url)
    instagram_extracted = InstagramService.extract_url_from_share_text(url)
    zhihu_extracted = ZhihuService.extract_url_from_share_text(url)
    pinterest_extracted = PinterestService.extract_url_from_share_text(url)
    reddit_extracted = RedditService.extract_url_from_share_text(url)
    
    if douyin_extracted:
        url = douyin_extracted
        content_type = 'douyin'
    elif weibo_extracted:
        url = weibo_extracted
        content_type = 'weibo'
    elif bilibili_extracted:
        url = bilibili_extracted
        content_type = 'bilibili'
    elif kuaishou_extracted:
        url = kuaishou_extracted
        content_type = 'kuaishou'
    elif instagram_extracted:
        url = instagram_extracted
        content_type = 'instagram'
    elif zhihu_extracted:
        url = ZhihuService.normalize_zhihu_url(zhihu_extracted)
        content_type = 'zhihu'
    elif pinterest_extracted:
        url = pinterest_extracted
        content_type = 'pinterest'
    elif reddit_extracted:
        url = reddit_extracted
        content_type = 'reddit'
    elif FeishuService.is_valid_feishu_url(url):
        content_type = 'feishu'
    elif YoutubeService.is_valid_youtube_url(url):
        content_type = 'youtube'
    elif ZhihuService.classify_zhihu_url(url):
        url = ZhihuService.normalize_zhihu_url(url)
        content_type = 'zhihu'
    elif PinterestService.is_valid_pinterest_url(url):
        content_type = 'pinterest'
    elif RedditService.is_valid_reddit_url(url):
        content_type = 'reddit'
    elif XHSService.is_valid_xhs_url(url):
        content_type = 'xhs'
    elif WechatService.is_valid_wechat_url(url):
        content_type = 'wechat'
    elif InstagramService.is_valid_instagram_url(url):
        content_type = 'instagram'
    elif WeiboService.is_valid_weibo_url(url):
        content_type = 'weibo'
    elif TwitterURLParser.is_valid_twitter_url(url):
        content_type = 'tweet'
    else:
        # Try XHS share text extraction (handles xhslink.com short URLs too)
        extracted = XHSService.extract_url_from_share_text(url)
        if extracted and extracted != url:
            extracted = XHSService.resolve_xhslink(extracted)
            extracted = XHSService.normalize_xhs_url(extracted)
        if extracted and XHSService.is_valid_xhs_url(extracted):
            url = extracted
            content_type = 'xhs'
        elif WebpageService.is_valid_webpage_url(url):
            content_type = 'webpage'
        else:
            return jsonify({'success': False, 'message': 'Unsupported URL. Please enter a valid http/https URL.'})

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
        task_dict.update(_analyze_task_error(task_dict.get('error_message'), task_dict.get('content_type')))
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


def _requeue_task_for_redownload(task_id: int):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        task = cursor.execute(
            'SELECT url FROM tasks WHERE id = ?',
            (task_id,)
        ).fetchone()

        if not task:
            return False, 'Task not found'

        task_url = task['url']
        cursor.execute("""
            UPDATE tasks SET
                status = 'pending',
                retry_count = 0,
                next_retry_time = NULL,
                processed_at = NULL,
                error_message = 'Manual redownload requested via Tasks page'
            WHERE id = ?
        """, (task_id,))
        conn.commit()
    finally:
        conn.close()

    enqueue_task(task_id, task_url)
    info(f"[Redownload] Task {task_id} requeued: {task_url}")
    return True, 'Task added to redownload queue'

@app.route('/saved')
@login_required
def saved():
    """已保存推文列表页面"""
    return render_template('saved.html')


@app.route('/search')
@login_required
def search():
    """搜索页面"""
    return render_template('search.html')


@app.route('/retries')
@login_required
def retries():
    return redirect(url_for('tasks'))

def _build_fts_query(q: str) -> str:
    """
    Convert a Google-style search string to an FTS5 MATCH expression.

    Supported syntax:
      - bare words          → AND (all must appear, not necessarily adjacent)
      - "exact phrase"      → phrase match
      - -word / -"phrase"   → NOT (exclude)
      - word1 OR word2      → OR

    Examples:
      金价 避险            →  "金价" "避险"
      金价 OR 白银         →  "金价" OR "白银"
      避险 -美联储         →  "避险" NOT "美联储"
      "避险资产" 黄金       →  "避险资产" "黄金"
    """
    import re as _re
    tokens = []
    # Tokenise: quoted phrases, -excluded terms, OR keyword, bare words
    for m in _re.finditer(r'-"([^"]+)"|"([^"]+)"|-(\S+)|(\bOR\b)|(\S+)', q):
        neg_phrase, phrase, neg_word, or_kw, word = m.groups()
        if neg_phrase:
            tokens.append(f'NOT "{neg_phrase}"')
        elif phrase:
            tokens.append(f'"{phrase}"')
        elif neg_word:
            tokens.append(f'NOT "{neg_word}"')
        elif or_kw:
            tokens.append('OR')
        elif word:
            tokens.append(f'"{word}"')

    # Collapse: insert implicit AND between consecutive non-OR tokens
    parts = []
    prev_was_op = True  # treat start as after an operator
    for tok in tokens:
        if tok == 'OR':
            parts.append('OR')
            prev_was_op = True
        elif tok.startswith('NOT '):
            if not prev_was_op and (not parts or parts[-1] != 'OR'):
                parts.append('AND')
            parts.append(tok)
            prev_was_op = False
        else:
            if not prev_was_op and (not parts or parts[-1] != 'OR'):
                parts.append('AND')
            parts.append(tok)
            prev_was_op = False

    return ' '.join(parts) if parts else f'"{q}"'


def _analyze_task_error(error_message: str, content_type: str = '') -> dict:
    text = (error_message or '').strip()
    lowered = text.lower()
    content_type = (content_type or '').lower()

    if not text:
        return {
            'likely_cookie_issue': False,
            'error_diagnosis': '',
        }

    cookie_tokens = (
        'cookie', 'cookies', 'auth_token', 'ct0', 'z_c0', 'web_session',
        'reddit_session', 'expired', 'invalid or expired', 'please refresh your cookie',
        'require a valid login cookie', 'login page', 'unauthorized', 'forbidden'
    )
    verification_tokens = ('captcha', 'verification', 'blocked the request', '403', '401')
    zhihu_request_shape_tokens = (
        '请求参数异常',
        '请升级客户端后重试',
        'code":10003',
        "code':10003",
        'article/api is blocked for this environment',
        'requires a different client path',
        'both cookie and no-cookie attempts',
    )

    likely_cookie_issue = any(token in lowered for token in cookie_tokens)
    verification_issue = any(token in lowered for token in verification_tokens)
    zhihu_request_shape_issue = content_type == 'zhihu' and any(token in text for token in zhihu_request_shape_tokens)

    if zhihu_request_shape_issue:
        likely_cookie_issue = False
        verification_issue = False

    diagnosis = ''
    if zhihu_request_shape_issue:
        diagnosis = 'Likely Zhihu API/article compatibility or anti-bot blocking issue, not a simple cookie expiry.'
    elif likely_cookie_issue or verification_issue:
        if content_type == 'xhs':
            diagnosis = 'Likely XHS cookies are missing or expired.'
        elif content_type == 'wechat':
            diagnosis = 'Likely WeChat login state expired, or verification/CAPTCHA blocked the request.'
        elif content_type == 'zhihu':
            diagnosis = 'Likely Zhihu z_c0 cookie expired, invalid, or blocked by CAPTCHA.'
        elif content_type == 'reddit':
            diagnosis = 'Likely Reddit session cookie expired or auth failed.'
        elif content_type in ('tweet', 'article'):
            diagnosis = 'Likely Twitter/X cookies expired or login state is invalid.'
        else:
            diagnosis = 'Likely cookie/login session issue.'
    elif 'rate limit' in lowered:
        diagnosis = 'Rate limit issue. Retrying later may succeed.'
    elif 'timeout' in lowered:
        diagnosis = 'Timeout while fetching content.'
    elif 'video download failed' in lowered:
        diagnosis = 'Media download step failed after metadata fetch.'

    return {
        'likely_cookie_issue': bool(likely_cookie_issue or verification_issue),
        'error_diagnosis': diagnosis,
    }


@app.route('/api/saved')
def api_saved():
    """获取已保存推文列表API，支持搜索功能"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search_query = request.args.get('search', '').strip()
    content_types = [ct.strip() for ct in request.args.get('content_type', '').split(',') if ct.strip()]
    # 'tweet' and 'article' are both Twitter content — treat them as one platform
    if 'tweet' in content_types and 'article' not in content_types:
        content_types.append('article')
    date_from = request.args.get('date_from', '').strip()   # 'YYYY-MM-DD'
    date_to = request.args.get('date_to', '').strip()        # 'YYYY-MM-DD'

    conn = get_db_connection()
    
    # 构建搜索条件
    base_where = "status = 'completed'"
    extra_conditions = []
    extra_params = []

    if content_types:
        placeholders = ','.join('?' * len(content_types))
        extra_conditions.append(f'content_type IN ({placeholders})')
        extra_params.extend(content_types)

    if date_from:
        extra_conditions.append('processed_at >= ?')
        extra_params.append(date_from + ' 00:00:00')

    if date_to:
        extra_conditions.append('processed_at <= ?')
        extra_params.append(date_to + ' 23:59:59')

    if extra_conditions:
        base_where = base_where + ' AND ' + ' AND '.join(extra_conditions)

    offset = (page - 1) * per_page

    if search_query:
        use_fts = len(search_query) >= 3
        if use_fts:
            # FTS5 trigram search (requires ≥3 unicode chars)
            # Parse Google-style syntax: "phrase", -exclude, OR, bare AND terms
            fts_query = _build_fts_query(search_query)
            query = f'''
                SELECT tasks.* FROM tasks
                JOIN tasks_fts ON tasks.id = tasks_fts.rowid
                WHERE tasks.{base_where} AND tasks_fts MATCH ?
                ORDER BY tasks.processed_at DESC
                LIMIT ? OFFSET ?
            '''
            params = extra_params + [fts_query, per_page, offset]
            tasks = conn.execute(query, params).fetchall()
            total = conn.execute(
                f"SELECT COUNT(*) as count FROM tasks JOIN tasks_fts ON tasks.id = tasks_fts.rowid WHERE tasks.{base_where} AND tasks_fts MATCH ?",
                extra_params + [fts_query]
            ).fetchone()['count']
        else:
            # Short query (<3 chars): trigram can't match, fallback to LIKE on FTS full_text
            like_param = f'%{search_query}%'
            query = f'''
                SELECT tasks.* FROM tasks
                JOIN tasks_fts ON tasks.id = tasks_fts.rowid
                WHERE tasks.{base_where}
                  AND (tasks_fts.title LIKE ? OR tasks_fts.full_text LIKE ? OR tasks_fts.author_name LIKE ? OR tasks_fts.author_username LIKE ?)
                ORDER BY tasks.processed_at DESC
                LIMIT ? OFFSET ?
            '''
            params = extra_params + [like_param, like_param, like_param, like_param, per_page, offset]
            tasks = conn.execute(query, params).fetchall()
            total = conn.execute(
                f'''SELECT COUNT(*) as count FROM tasks
                   JOIN tasks_fts ON tasks.id = tasks_fts.rowid
                   WHERE tasks.{base_where}
                     AND (tasks_fts.title LIKE ? OR tasks_fts.full_text LIKE ? OR tasks_fts.author_name LIKE ? OR tasks_fts.author_username LIKE ?)''',
                extra_params + [like_param, like_param, like_param, like_param]
            ).fetchone()['count']
    else:
        query = f'''
            SELECT * FROM tasks
            WHERE {base_where}
            ORDER BY processed_at DESC
            LIMIT ? OFFSET ?
        '''
        tasks = conn.execute(query, extra_params + [per_page, offset]).fetchall()
        total = conn.execute(f"SELECT COUNT(*) as count FROM tasks WHERE {base_where}", extra_params).fetchone()['count']
    
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
                    if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
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

            # YouTube / WeChat / XHS: show title as preview
            if _ct == 'youtube':
                task_dict['preview_text'] = task_dict.get('tweet_text') or ''
            elif _ct in ('wechat', 'xhs'):
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
    debug(f"[View] /view/{slug} - is_logged_in={is_logged_in}, session_keys={list(dict(session).keys())}")

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
            warning(f"[View] Failed to read content.txt for slug {slug}: {e}")
            tweet_text = ""

    # 读取Reader模式HTML内容
    tweet_html = ""
    content_html_file = os.path.join(actual_save_path, 'content.html')
    if os.path.exists(content_html_file):
        try:
            with open(content_html_file, 'r', encoding='utf-8') as f:
                html_content = f.read()
                # 提取HTML文件中的推文内容部分（去掉HTML文档结构）
                from bs4 import BeautifulSoup as _BS
                _soup = _BS(html_content, 'html.parser')
                _reader = _soup.find('div', class_='reader-content')
                if _reader:
                    tweet_html = str(_reader)
                    debug(f"[View] Loaded Reader mode content for slug {slug}, length={len(tweet_html)}")
                else:
                    _body = _soup.find('body')
                    tweet_html = _body.decode_contents() if _body else html_content
                    debug(f"[View] Using fallback HTML content for slug {slug}, length={len(tweet_html)}")
        except Exception as e:
            warning(f"[View] Failed to read HTML file for slug {slug}: {e}")
            tweet_html = ""

    # 构造推文数据
    content_type = 'tweet'
    try:
        content_type = task['content_type'] or 'tweet'
    except (IndexError, KeyError):
        pass

    # Thread-style content (generated by save_thread_content for xreach tweets, single or multi):
    # fix up relative media paths in content.html to /media/<task_id>/...
    _has_thread_html = content_type == 'tweet' and tweet_html and 'thread-tweet' in tweet_html
    if _has_thread_html:
        tweet_html = re.sub(
            r'(?:src|href)="(images/[^"]+|videos/[^"]+)"',
            lambda m: f'src="/media/{task_id}/{m.group(1)}"',
            tweet_html
        )

    # Webpage: rewrite relative image paths to /media/<task_id>/images/...
    if content_type == 'webpage' and tweet_html:
        tweet_html = re.sub(
            r'src="(images/[^"]+)"',
            lambda m: f'src="/media/{task_id}/{m.group(1)}"',
            tweet_html
        )

    # XHS / WeChat articles: render content.md as HTML with local image paths
    if content_type in ('xhs', 'wechat', 'douyin', 'weibo', 'bilibili', 'kuaishou', 'instagram', 'zhihu', 'pinterest', 'reddit', 'feishu') and not tweet_html:
        content_md_file = os.path.join(actual_save_path, 'content.md')
        if os.path.exists(content_md_file):
            try:
                import re as _re
                import markdown as _md
                md_text = open(content_md_file, encoding='utf-8').read()
                # Strip source URL lines and XHS-specific noise fields
                md_text = _re.sub(r'\*\*(来源|链接)\*\*:.*\n?', '', md_text)
                if content_type == 'xhs':
                    md_text = _re.sub(r'\*\*IP归属\*\*:.*\n?', '', md_text)
                    md_text = _re.sub(r'\*\*类型\*\*:.*\n?', '', md_text)
                    md_text = _re.sub(r'\*\*点赞\*\*:.*\n?', '', md_text)
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
                # Rewrite Douyin/YouTube-style video.mp4 path
                md_text = _re.sub(
                    r'videos/(video\.\w+)',
                    lambda m: f'/media/{task_id}/videos/{m.group(1)}',
                    md_text
                )
                # Auto-link bare URLs in description (skip already-linked ones)
                md_text = _re.sub(
                    r'(?<!\]\()(https?://[^\s<>\[\]()]+)',
                    r'[\1](\1)',
                    md_text
                )
                tweet_html = _md.markdown(md_text, extensions=['nl2br', 'tables'])
                # Replace video links with inline <video> players
                tweet_html = _re.sub(
                    r'<a href="(/media/\d+/videos/video[\d.]*\.[^"]+)">视频[^<]*</a>',
                    lambda m: (
                        f'<video controls style="max-width:100%;margin:8px 0">'
                        f'<source src="{m.group(1)}" type="video/mp4"></video>'
                    ),
                    tweet_html
                )
            except Exception as e:
                warning(f"[View] Markdown render failed for {content_type} slug {slug}: {e}")

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
                # Auto-link bare URLs in description (skip already-linked ones)
                md_text = re.sub(
                    r'(?<!\]\()(https?://[^\s<>\[\]()]+)',
                    r'[\1](\1)',
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
                warning(f"[View] YouTube markdown render failed for slug {slug}: {e}")

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

    # WeChat/YouTube/webpage/thread-style tweet: media is already inline in HTML — suppress separate grid
    display_media_files = [] if (
        content_type in ('wechat', 'youtube', 'douyin', 'weibo', 'bilibili', 'kuaishou', 'webpage', 'instagram', 'zhihu', 'pinterest', 'reddit', 'feishu') and tweet_html
    ) or _has_thread_html else media_files

    # Check for transcript
    has_transcript = os.path.exists(os.path.join(actual_save_path, 'transcript.txt'))

    # 提取页面标题：优先读 metadata.json 的 title 字段，其次用内容首行，最后按 content_type 兜底
    page_title = ''
    metadata_json_file = os.path.join(actual_save_path, 'metadata.json')
    if os.path.exists(metadata_json_file):
        try:
            import json as _json
            with open(metadata_json_file, 'r', encoding='utf-8') as _f:
                _meta = _json.load(_f)
            page_title = _meta.get('title', '') or ''
        except Exception:
            pass
    if not page_title and tweet_text:
        first_line = tweet_text.splitlines()[0].lstrip('#').strip()
        if first_line:
            page_title = first_line[:80] + ('…' if len(first_line) > 80 else '')
    if not page_title:
        _type_labels = {'tweet': 'Tweet', 'article': 'Article', 'xhs': 'XHS Post',
                        'wechat': 'WeChat Article', 'youtube': 'YouTube Video', 'webpage': 'Webpage',
                        'douyin': 'Douyin/TikTok', 'weibo': 'Weibo Post', 'bilibili': 'Bilibili Video',
                        'kuaishou': 'Kuaishou Video', 'zhihu': 'Zhihu Post',
                        'pinterest': 'Pinterest Pin', 'reddit': 'Reddit Post',
                        'feishu': '飞书文档'}
        page_title = _type_labels.get(content_type, 'Content')

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
        'page_title': page_title,
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

@app.route('/debug', endpoint='debug')
@login_required
def debug_page():
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
            warning(f"[Reset] Found {len(stuck_tasks)} stuck tasks")
            # 重置为pending
            conn.execute('UPDATE tasks SET status = "pending" WHERE status = "processing"')
            conn.commit()
            
            # 重新加入队列
            for task in stuck_tasks:
                enqueue_task(task['id'], task['url'])
                info(f"[Reset] Requeued task {task['id']}")
            
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
        warning("[Force Start] Force starting queue processor")
        
        # 检查线程状态
        thread_alive = processing_thread.is_alive() if processing_thread else False
        info(f"[Force Start] Thread alive: {thread_alive}")
        
        # 强制重置所有processing任务为pending
        conn = get_db_connection()
        processing_tasks = conn.execute(
            'SELECT id FROM tasks WHERE status = "processing"'
        ).fetchall()
        
        if processing_tasks:
            warning(f"[Force Start] Resetting {len(processing_tasks)} processing tasks to pending")
            conn.execute('UPDATE tasks SET status = "pending" WHERE status = "processing"')
            conn.commit()
        
        conn.close()
        
        # 重新启动线程（如果需要）
        if not thread_alive:
            info("[Force Start] Starting queue processor thread")
            start_background_thread()
            
        # 重新加载待处理任务
        info("[Force Start] Reloading pending tasks")
        load_pending_tasks()
        
        queue_size = processing_queue.qsize()
        success(f"[Force Start] Queue size after reload: {queue_size}")
        
        return jsonify({
            'success': True,
            'message': f'Queue processor restarted. Thread alive: {processing_thread.is_alive() if processing_thread else False}, Queue size: {queue_size}',
            'queue_size': queue_size
        })
    except Exception as e:
        error(f"[Force Start] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })

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

# Flask应用启动时的钩子
@app.before_request
def initialize_app():
    """应用请求前的初始化"""
    if not hasattr(app, '_services_initialized'):
        info("[Flask] First request - initializing services in Flask context")
        debug(f"[Flask] Globals before init: config_manager={config_manager is not None}, twitter_service={twitter_service is not None}")
        
        result = init_services()
        info(f"[Flask] init_services() returned: {result}")
        debug(f"[Flask] Globals after init: config_manager={config_manager is not None}, twitter_service={twitter_service is not None}")
        
        if not result:
            error("[Flask] Failed to initialize services in Flask context")
        else:
            success("[Flask] Services initialized successfully in Flask context")
        app._services_initialized = True
    
    if not hasattr(app, '_background_thread_started'):
        info("[Flask] First request - initializing background thread")
        start_background_thread()
        # 自动检测并修复卡住的任务
        auto_fix_stuck_tasks()
        app._background_thread_started = True

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
    """兼容旧接口，内部统一按 redownload 逻辑重入队。"""
    try:
        success, message = _requeue_task_for_redownload(task_id)
        return jsonify({'success': success, 'message': message})
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


@app.route('/api/redownload/<int:task_id>', methods=['POST'])
@login_required
def api_redownload(task_id):
    """强制重新下载指定任务"""
    try:
        success, message = _requeue_task_for_redownload(task_id)
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Redownload failed: {str(e)}'})
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
        # --- API Key auth ---
        provided = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            provided = auth_header[7:]
        if not provided and request.is_json:
            body = request.get_json(silent=True) or {}
            provided = body.get('api_key')
        if not check_api_key(provided or ''):
            return jsonify({'success': False, 'error': 'Unauthorized',
                            'message': 'Valid API key required'}), 401
        # --- end auth ---

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
            if text_data:
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
        
        # Detect content type (same logic as submit_url)
        _ct = 'tweet'
        
        douyin_extracted = DouyinService.extract_url_from_share_text(url)
        weibo_extracted = WeiboService.extract_url_from_share_text(url)
        bilibili_extracted = BilibiliService.extract_url_from_share_text(url)
        kuaishou_extracted = KuaishouService.extract_url_from_share_text(url)
        instagram_extracted = InstagramService.extract_url_from_share_text(url)
        zhihu_extracted = ZhihuService.extract_url_from_share_text(url)
        pinterest_extracted = PinterestService.extract_url_from_share_text(url)
        reddit_extracted = RedditService.extract_url_from_share_text(url)

        if douyin_extracted:
            url = douyin_extracted
            _ct = 'douyin'
        elif weibo_extracted:
            url = weibo_extracted
            _ct = 'weibo'
        elif bilibili_extracted:
            url = bilibili_extracted
            _ct = 'bilibili'
        elif kuaishou_extracted:
            url = kuaishou_extracted
            _ct = 'kuaishou'
        elif instagram_extracted:
            url = instagram_extracted
            _ct = 'instagram'
        elif zhihu_extracted:
            url = ZhihuService.normalize_zhihu_url(zhihu_extracted)
            _ct = 'zhihu'
        elif pinterest_extracted:
            url = pinterest_extracted
            _ct = 'pinterest'
        elif reddit_extracted:
            url = reddit_extracted
            _ct = 'reddit'
        elif ZhihuService.classify_zhihu_url(url):
            url = ZhihuService.normalize_zhihu_url(url)
            _ct = 'zhihu'
        elif PinterestService.is_valid_pinterest_url(url):
            _ct = 'pinterest'
        elif RedditService.is_valid_reddit_url(url):
            _ct = 'reddit'
        elif FeishuService.is_valid_feishu_url(url):
            _ct = 'feishu'
        elif YoutubeService.is_valid_youtube_url(url):
            _ct = 'youtube'
        elif XHSService.is_valid_xhs_url(url):
            _ct = 'xhs'
        elif WechatService.is_valid_wechat_url(url):
            _ct = 'wechat'
        elif InstagramService.is_valid_instagram_url(url):
            _ct = 'instagram'
        elif WeiboService.is_valid_weibo_url(url):
            _ct = 'weibo'
        elif TwitterURLParser.is_valid_twitter_url(url):
            _ct = 'tweet'
        else:
            extracted = XHSService.extract_url_from_share_text(url)
            if extracted and extracted != url:
                extracted = XHSService.resolve_xhslink(extracted)
                extracted = XHSService.normalize_xhs_url(extracted)
            if extracted and XHSService.is_valid_xhs_url(extracted):
                url = extracted
                _ct = 'xhs'
            elif WebpageService.is_valid_webpage_url(url):
                _ct = 'webpage'
            else:
                return jsonify({
                    'success': False,
                    'error': 'Unsupported URL',
                    'message': f'Cannot process URL: {url}',
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
            'INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, ?, ?, ?)',
            (url, 'pending', format_time_for_db(get_current_time()), _ct)
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # 添加到处理队列
        enqueue_task(task_id, url)
        info(f"[API Submit] Added {_ct} task {task_id} to queue. Queue size: {processing_queue.qsize()}")
        
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



# ---------------------------------------------------------------------------
# App settings helpers
# ---------------------------------------------------------------------------


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


@app.route('/api/settings/api-key', methods=['GET'])
@login_required
def api_key_get():
    key = get_setting('api_key', '')
    return jsonify({'has_key': bool(key), 'key_preview': key[:8] + '...' if key else ''})


@app.route('/api/settings/api-key/generate', methods=['POST'])
@login_required
def api_key_generate():
    import secrets
    new_key = secrets.token_hex(32)
    set_setting('api_key', new_key)
    return jsonify({'success': True, 'key': new_key})


@app.route('/api/settings/api-key', methods=['DELETE'])
@login_required
def api_key_revoke():
    set_setting('api_key', '')
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


@app.route('/api/twitter/cookie-status')
@login_required
def api_twitter_cookie_status():
    """Check Twitter cookie configuration status."""
    auth_token = config_manager.get_twitter_auth_token() if config_manager else None
    ct0 = config_manager.get_twitter_ct0() if config_manager else None
    configured = bool(auth_token and ct0)
    return jsonify({
        'configured': configured,
        'auth_token_preview': (auth_token[:8] + '…') if auth_token else None,
    })


@app.route('/api/twitter/cookies', methods=['POST'])
@login_required
def api_twitter_save_cookies():
    """Save Twitter cookies from Cookie-Editor JSON export.

    Accepts a JSON array exported by Cookie-Editor. Extracts auth_token and ct0,
    saves them to config.ini, and re-initialises TwitterService.
    """
    data = request.get_json()
    if not data or not data.get('cookies'):
        return jsonify({'success': False, 'message': 'No cookie data provided'}), 400

    try:
        cookies = json.loads(data['cookies'])
        if not isinstance(cookies, list):
            return jsonify({'success': False, 'message': 'Expected a JSON array of cookies'}), 400

        cookie_map = {c['name']: c['value'] for c in cookies if 'name' in c and 'value' in c}
        auth_token = cookie_map.get('auth_token', '')
        ct0 = cookie_map.get('ct0', '')

        if not auth_token or not ct0:
            return jsonify({'success': False, 'message': 'auth_token or ct0 not found in cookie data'}), 400

        config_manager.set_twitter_cookies(auth_token, ct0)

        # Re-initialise TwitterService with the new credentials
        global twitter_service
        if twitter_service:
            twitter_service.xreach_auth_token = auth_token
            twitter_service.xreach_ct0 = ct0
            import shutil
            twitter_service.use_xreach = bool(shutil.which('xreach'))
        init_services()

        return jsonify({'success': True, 'message': 'Twitter cookies updated successfully'})
    except json.JSONDecodeError:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/reddit/cookie-status')
@login_required
def api_reddit_cookie_status():
    """Check Reddit cookie file status."""
    cookies_path = RedditService.get_cookies_path()
    if os.path.exists(cookies_path):
        mtime = os.path.getmtime(cookies_path)
        modified = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open(cookies_path, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            count = len(cookies) if isinstance(cookies, list) else 0
        except Exception:
            count = 0
        return jsonify({'exists': True, 'modified': modified, 'count': count})
    return jsonify({'exists': False})


@app.route('/api/reddit/cookies', methods=['POST'])
@login_required
def api_reddit_save_cookies():
    """Save Reddit cookies from Cookie-Editor JSON export."""
    data = request.get_json()
    if not data or not data.get('cookies'):
        return jsonify({'success': False, 'message': 'No cookie data provided'}), 400

    try:
        cookies = json.loads(data['cookies'])
        if not isinstance(cookies, list):
            return jsonify({'success': False, 'message': 'Expected a JSON array of cookies'}), 400

        cookie_map = {c['name']: c['value'] for c in cookies if isinstance(c, dict) and 'name' in c and 'value' in c}
        if not cookie_map.get('reddit_session'):
            return jsonify({'success': False, 'message': 'reddit_session not found in cookie data'}), 400

        cookies_path = RedditService.get_cookies_path()
        os.makedirs(os.path.dirname(cookies_path), exist_ok=True)
        with open(cookies_path, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        return jsonify({'success': True, 'message': f'Saved {len(cookies)} cookies.'})
    except json.JSONDecodeError:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/zhihu/cookie', methods=['GET'])
@login_required
def api_zhihu_cookie_get():
    """Get Zhihu z_c0 cookie status."""
    z_c0 = config_manager.get_config('zhihu', 'z_c0', fallback='') if config_manager else ''
    return jsonify({
        'configured': bool(z_c0),
        'value_preview': (z_c0[:10] + '...') if z_c0 else ''
    })


@app.route('/api/zhihu/cookie', methods=['POST'])
@login_required
def api_zhihu_cookie_post():
    """Save Zhihu z_c0 cookie extracted from Cookie-Editor JSON export."""
    data = request.get_json() or {}
    cookies_str = data.get('cookies', '')
    if not cookies_str:
        return jsonify({'success': False, 'message': 'No cookie data provided'}), 400
    try:
        cookies = json.loads(cookies_str)
        if not isinstance(cookies, list):
            return jsonify({'success': False, 'message': 'Expected a JSON array of cookies'}), 400
        cookie_map = {c['name']: c['value'] for c in cookies if 'name' in c and 'value' in c}
        z_c0 = cookie_map.get('z_c0', '').strip()
        if not z_c0:
            return jsonify({'success': False, 'message': 'z_c0 cookie not found in the provided JSON'}), 400
        # Save full cookie list to file (all cookies needed for Zhihu auth)
        cookie_file = os.path.join(DATA_DIR, 'zhihu_cookies.json')
        with open(cookie_file, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        # Delete the persistent browser profile so the next run rebuilds it with
        # the fresh cookies just provided.
        profile_dir = os.path.join(DATA_DIR, 'zhihu_profile')
        if os.path.exists(profile_dir):
            import shutil as _shutil
            _shutil.rmtree(profile_dir, ignore_errors=True)
        # Also save z_c0 to config for status display
        if config_manager:
            config_manager.set_config('zhihu', 'z_c0', z_c0)
        return jsonify({'success': True, 'message': f'Saved {len(cookies)} cookies (including z_c0)'})
    except json.JSONDecodeError:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400


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
        yield "event: status\ndata: connected\n\n"

        # 发送已有的日志
        for log_entry in get_formatted_logs():
            yield f"data: {log_entry}\n\n"

        # 实时推送新日志
        last_seq = get_latest_seq()
        idle_ticks = 0
        while True:
            try:
                new_logs = get_logs_after(last_seq)
                if new_logs:
                    for log_entry in new_logs:
                        yield f"data: {format_log_entry(log_entry)}\n\n"
                    last_seq = new_logs[-1]['seq']
                    idle_ticks = 0
                else:
                    idle_ticks += 1

                # 每15秒发一次心跳，防止代理超时断连
                if idle_ticks >= 30:
                    yield "event: ping\ndata: keepalive\n\n"
                    idle_ticks = 0

                time.sleep(0.5)
            except GeneratorExit:
                break
            except Exception as e:
                yield f"data: [ERROR] 日志流错误: {str(e)}\n\n"
                break
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
        'Access-Control-Allow-Origin': '*'
    })

@app.route('/api/logs/recent')
def get_recent_logs():
    """获取最近的日志（用于初始化）"""
    return jsonify({
        'success': True,
        'logs': get_formatted_logs()
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
    cfg = cp.ConfigParser(interpolation=None)
    if os.path.exists('config.ini'):
        cfg.read('config.ini')
    token_configured = bool(cfg.get('telegram', 'bot_token', fallback='').strip())
    enabled = cfg.get('telegram', 'enabled', fallback='true').strip().lower() != 'false'
    status = get_status()
    status['token_configured'] = token_configured
    status['enabled'] = enabled
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

    cfg = cp.ConfigParser(interpolation=None)
    if os.path.exists('config.ini'):
        cfg.read('config.ini')
    if 'telegram' not in cfg:
        cfg['telegram'] = {}
    cfg['telegram']['bot_token'] = token
    with open('config.ini', 'w') as f:
        cfg.write(f)

    start_bot(token, _telegram_submit)
    return jsonify({'success': True, 'message': 'Token saved and bot started'})


@app.route('/api/telegram/toggle', methods=['POST'])
@login_required
def telegram_toggle():
    """Enable or disable the Telegram bot."""
    import configparser as cp
    from services.telegram_bot import start_bot, stop_bot
    data = request.get_json() or {}
    enabled = bool(data.get('enabled', True))

    cfg = cp.ConfigParser(interpolation=None)
    if os.path.exists('config.ini'):
        cfg.read('config.ini')
    if 'telegram' not in cfg:
        cfg['telegram'] = {}
    cfg['telegram']['enabled'] = 'true' if enabled else 'false'
    with open('config.ini', 'w') as f:
        cfg.write(f)

    token = cfg.get('telegram', 'bot_token', fallback='').strip()
    if enabled and token:
        start_bot(token, _telegram_submit)
        return jsonify({'success': True, 'message': 'Bot enabled and started'})
    elif not enabled:
        stop_bot()
        return jsonify({'success': True, 'message': 'Bot disabled and stopped'})
    else:
        return jsonify({'success': True, 'message': 'Bot enabled (no token configured)'})


@app.route('/api/telegram/reset-owner', methods=['POST'])
@login_required
def telegram_reset_owner():
    """Clear the registered owner so the next /start registers a new one."""
    from services.telegram_bot import clear_owner
    clear_owner()
    return jsonify({'success': True, 'message': 'Owner reset'})


# Re-exports for run_web.py backwards compatibility
from services.db import init_db, get_db_connection, rebuild_fts_index, get_setting  # noqa: F401
from services.background import start_background_thread, load_pending_tasks, start_xhs_autosave  # noqa: F401

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
            info(f"[FTS] Index empty, rebuilding from {_tasks_count} completed tasks")
            n = rebuild_fts_index()
            success(f"[FTS] Indexed {n} entries")
    except Exception as e:
        warning(f"[FTS] Could not check/rebuild index: {e}")

    # 初始化服务
    if not init_services():
        error("[Startup] Failed to initialize services. Please check your configuration.")
        exit(1)
    
    # 启动队列处理线程
    start_background_thread()
    
    # 加载待处理任务
    load_pending_tasks()
    
    info("[Startup] Twitter Saver Web App starting")
    info("[Startup] Access the application at: http://localhost:6201")

    app.run(debug=False, host='0.0.0.0', port=6201)

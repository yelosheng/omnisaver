import os
import queue
import threading
import time
import traceback
from datetime import timedelta

from services.db import (
    get_db_connection, get_current_time, format_time_for_db,
    generate_unique_slug, fts_upsert, _read_full_text, _read_title,
    get_setting, set_setting,
)
from utils.realtime_logger import info, error, warning, success

# ── 服务依赖（由 init_background() 注入） ─────────────────────────────
_config_manager = None
_twitter_service = None
_media_downloader = None
_file_manager = None

# DATA_DIR needed for fallback paths in make_* helpers
DATA_DIR = os.environ.get('DATA_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def init_background(config_manager, twitter_service, media_downloader, file_manager):
    """在 init_services() 之后调用，注入外部服务引用。"""
    global _config_manager, _twitter_service, _media_downloader, _file_manager
    _config_manager   = config_manager
    _twitter_service  = twitter_service
    _media_downloader = media_downloader
    _file_manager     = file_manager


# ── 队列全局变量 ──────────────────────────────────────────────────────
processing_queue = queue.Queue()
is_processing = False
_queued_task_ids = set()  # Track task IDs currently in the queue to prevent duplicates
_queued_task_ids_lock = threading.Lock()
processing_thread = None

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

MAX_TASK_ERROR_MESSAGE_LENGTH = 4000


def _truncate_task_error_message(message: str, limit: int = MAX_TASK_ERROR_MESSAGE_LENGTH) -> str:
    if not message:
        return ''
    if len(message) <= limit:
        return message
    return message[: limit - 15] + '\n... [truncated]'


def _build_task_error_details(exc: Exception, *, task_id: int, url: str = '', stage: str = '') -> str:
    exc_type = type(exc).__name__
    exc_message = (str(exc) or repr(exc)).strip()
    tb = traceback.format_exc().strip()

    lines = [f'Task ID: {task_id}']
    if stage:
        lines.append(f'Stage: {stage}')
    if url:
        lines.append(f'URL: {url}')
    lines.append(f'Exception: {exc_type}')
    lines.append(f'Message: {exc_message or "(empty error message)"}')

    lowered = exc_message.lower()
    is_request_shape_issue = any(token in exc_message for token in (
        '请求参数异常',
        '请升级客户端后重试',
        'code":10003',
        "code':10003",
    ))
    if any(token in lowered for token in (
        'cookie', 'cookies', 'auth_token', 'ct0', 'z_c0', 'web_session',
        'reddit_session', 'expired', 'invalid or expired', 'login page',
        'please refresh your cookie', 'require a valid login cookie',
        'unauthorized', 'forbidden', 'captcha', 'verification'
    )) and not is_request_shape_issue:
        lines.append('Diagnosis: likely cookie/login session issue. Refresh the related site cookies and retry.')
    elif is_request_shape_issue:
        lines.append('Diagnosis: likely Zhihu API/article compatibility or anti-bot blocking issue, not a simple cookie expiry.')

    if tb and tb != 'NoneType: None':
        lines.extend(['', 'Traceback:', tb])

    return _truncate_task_error_message('\n'.join(lines))


def _store_task_failure(task_id: int, exc: Exception, *, url: str = '', stage: str = '') -> str:
    details = _build_task_error_details(exc, task_id=task_id, url=url, stage=stage)
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE tasks SET status='failed', error_message=? WHERE id=?",
            (details, task_id)
        )
        conn.commit()
    finally:
        conn.close()
    return details

_xhs_autosave_thread: threading.Thread = None
_xhs_autosave_stop = threading.Event()


def enqueue_task(task_id: int, url: str) -> bool:
    """Add a task to the processing queue. Returns False if already queued."""
    with _queued_task_ids_lock:
        if task_id in _queued_task_ids:
            return False
        _queued_task_ids.add(task_id)
    processing_queue.put((task_id, url))
    return True


def check_and_schedule_retry(cursor, task_id, error_message, error_details=None):
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
            "Request failed",
            "Video download failed",
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
                _truncate_task_error_message(
                    f"Retry {retry_count + 1}/{max_retries}\n"
                    f"Original error: {error_message}\n\n"
                    f"{error_details or error_message}"
                ),
                task_id
            ))

            warning(
                f"[Task {task_id}] Scheduled for retry {retry_count + 1}/{max_retries} "
                f"at {next_retry_time.strftime('%Y-%m-%d %H:%M:%S')}: {error_message}"
            )
            return True
        else:
            warning(f"[Task {task_id}] Retry skipped: max retries reached or error not retry-eligible: {error_message}")
            return False

    except Exception as e:
        error(f"Error in check_and_schedule_retry: {e}")
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


def get_xhs_save_path() -> str:
    """Return the XHS base save directory — same as Twitter's save path."""
    if _config_manager:
        return _config_manager.get_save_path()
    return os.path.join(DATA_DIR, 'saved_tweets')


def make_xhs_service():
    """Instantiate XHSService with the same path/folder settings as Twitter."""
    from services.xhs_service import XHSService
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    return XHSService(get_xhs_save_path(), create_date_folders=create_date_folders)


def register_xhs_task(url: str, result: dict) -> tuple:
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


def make_wechat_service():
    """Instantiate WechatService with the same path/folder settings as Twitter."""
    from services.wechat_service import WechatService
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    return WechatService(base_path, create_date_folders=create_date_folders)


def register_wechat_task(url: str, result: dict) -> tuple:
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


def make_youtube_service():
    """Instantiate YoutubeService with the same path/folder settings as Twitter."""
    from services.youtube_service import YoutubeService
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    yt_api_key = _config_manager.get_youtube_api_key() if _config_manager else None
    return YoutubeService(base_path, create_date_folders=create_date_folders,
                          youtube_api_key=yt_api_key)


def make_webpage_service():
    """Instantiate WebpageService with the configured save path."""
    from services.webpage_service import WebpageService
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    return WebpageService(base_path)


def make_douyin_service():
    """Instantiate DouyinService with configured save path and cookie."""
    from services.douyin_service import DouyinService
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    return DouyinService(base_path, create_date_folders=create_date_folders)


def make_weibo_service():
    """Instantiate WeiboService with configured save path."""
    from services.weibo_service import WeiboService
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    return WeiboService(base_path, create_date_folders=create_date_folders)


def make_bilibili_service():
    """Instantiate BilibiliService with configured save path."""
    from services.bilibili_service import BilibiliService
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    return BilibiliService(base_path, create_date_folders=create_date_folders)


def make_kuaishou_service():
    """Instantiate KuaishouService with configured save path."""
    from services.kuaishou_service import KuaishouService
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    return KuaishouService(base_path, create_date_folders=create_date_folders)


def make_instagram_service():
    """Instantiate InstagramService with configured save path."""
    from services.instagram_service import InstagramService
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    return InstagramService(base_path, create_date_folders=create_date_folders)


def make_zhihu_service():
    """Instantiate ZhihuService with configured save path."""
    from services.zhihu_service import ZhihuService
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    return ZhihuService(base_path, create_date_folders=create_date_folders)


def make_pinterest_service():
    """Instantiate PinterestService with configured save path."""
    from services.pinterest_service import PinterestService
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    return PinterestService(base_path, create_date_folders=create_date_folders)


def make_reddit_service():
    """Instantiate RedditService with configured save path."""
    from services.reddit_service import RedditService
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    return RedditService(base_path, create_date_folders=create_date_folders)


def process_zhihu_task(task_id: int, url: str):
    """Queue worker handler for Zhihu tasks."""
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        svc = make_zhihu_service()
        result = svc.save_post(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?,
               author_username=?, author_name=?, save_path=?, tweet_text=?,
               share_slug=?, media_count=?, content_type='zhihu' WHERE id=?''',
            (now, result['post_id'],
             result.get('author_username', ''), result.get('author_name', ''),
             result['save_path'], result.get('tweet_text', '')[:500],
             slug, result.get('media_count', 0),
             task_id)
        )

        full_text = _read_full_text(result['save_path']) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''),
                   full_text, title=result.get('title'))
        conn.commit()
        conn.close()
        success(f'[Zhihu Task {task_id}] Saved: {result.get("title", url)}')

    except Exception as e:
        error(f'[Zhihu Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='zhihu save')
        except Exception:
            pass


def process_instagram_task(task_id: int, url: str):
    """Queue worker handler for Instagram tasks."""
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        svc = make_instagram_service()
        result = svc.save_video(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?, 
               author_username=?, author_name=?, save_path=?, tweet_text=?, 
               share_slug=?, media_count=?, content_type='instagram' WHERE id=?''',
            (now, result['video_id'],
             result.get('author_username', ''), result.get('author_name', ''),
             result['save_path'], result.get('tweet_text', '')[:500],
             slug, result.get('media_count', 0),
             task_id)
        )

        full_text = _read_full_text(result['save_path']) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''),
                   full_text, title=result.get('title'))
        conn.commit()
        conn.close()
        success(f'[Instagram Task {task_id}] Saved: {result.get("title", url)}')

    except Exception as e:
        error(f'[Instagram Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='instagram save')
        except Exception:
            pass


def process_pinterest_task(task_id: int, url: str):
    """Queue worker handler for Pinterest tasks."""
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        svc = make_pinterest_service()
        result = svc.save_pin(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?,
               author_username=?, author_name=?, save_path=?, tweet_text=?,
               share_slug=?, media_count=?, content_type='pinterest' WHERE id=?''',
            (now, result['pin_id'],
             result.get('author_username', ''), result.get('author_name', ''),
             result['save_path'], result.get('tweet_text', '')[:500],
             slug, result.get('media_count', 0),
             task_id)
        )
        full_text = _read_full_text(result['save_path']) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''),
                   full_text, title=_read_title(result['save_path']))
        conn.commit()
        conn.close()
        success(f'[Pinterest Task {task_id}] Saved: {result.get("title", url)}')

    except Exception as e:
        error(f'[Pinterest Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='pinterest save')
        except Exception:
            pass


def process_reddit_task(task_id: int, url: str):
    """Queue worker handler for Reddit tasks."""
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        svc = make_reddit_service()
        result = svc.save_post(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?,
               author_username=?, author_name=?, save_path=?, tweet_text=?,
               share_slug=?, media_count=?, content_type='reddit' WHERE id=?''',
            (now, result['post_id'],
             result.get('author_username', ''), result.get('author_name', ''),
             result['save_path'], result.get('tweet_text', '')[:500],
             slug, result.get('media_count', 0),
             task_id)
        )
        full_text = _read_full_text(result['save_path']) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''),
                   full_text, title=_read_title(result['save_path']))
        conn.commit()
        conn.close()
        success(f'[Reddit Task {task_id}] Saved: {result.get("title", url)}')

    except Exception as e:
        error(f'[Reddit Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='reddit save')
        except Exception:
            pass


def process_kuaishou_task(task_id: int, url: str):
    """Queue worker handler for Kuaishou tasks."""
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        svc = make_kuaishou_service()
        result = svc.save_video(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?, 
               author_username=?, author_name=?, save_path=?, tweet_text=?, 
               share_slug=?, media_count=?, content_type='kuaishou' WHERE id=?''',
            (now, result['video_id'],
             result.get('author_username', ''), result.get('author_name', ''),
             result['save_path'], result.get('tweet_text', '')[:500],
             slug, result.get('media_count', 0),
             task_id)
        )

        full_text = _read_full_text(result['save_path']) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''),
                   full_text, title=result.get('title'))
        conn.commit()
        conn.close()
        success(f'[Kuaishou Task {task_id}] Saved: {result.get("title", url)}')

    except Exception as e:
        error(f'[Kuaishou Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='kuaishou save')
        except Exception:
            pass


def process_bilibili_task(task_id: int, url: str):
    """Queue worker handler for Bilibili tasks."""
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        svc = make_bilibili_service()
        result = svc.save_video(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?, 
               author_username=?, author_name=?, save_path=?, tweet_text=?, 
               share_slug=?, media_count=?, content_type='bilibili' WHERE id=?''',
            (now, result['video_id'],
             result.get('author_username', ''), result.get('author_name', ''),
             result['save_path'], result.get('tweet_text', '')[:500],
             slug, result.get('media_count', 0),
             task_id)
        )

        full_text = _read_full_text(result['save_path']) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''),
                   full_text, title=result.get('title'))
        conn.commit()
        conn.close()
        success(f'[Bilibili Task {task_id}] Saved: {result.get("title", url)}')

    except Exception as e:
        error(f'[Bilibili Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='bilibili save')
        except Exception:
            pass


def process_weibo_task(task_id: int, url: str):
    """Queue worker handler for Weibo tasks."""
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        svc = make_weibo_service()
        result = svc.save_post(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?, 
               author_username=?, author_name=?, save_path=?, tweet_text=?, 
               share_slug=?, media_count=?, content_type='weibo' WHERE id=?''',
            (now, result['post_id'],
             result.get('author_username', ''), result.get('author_name', ''),
             result['save_path'], result.get('tweet_text', '')[:500],
             slug, result.get('media_count', 0),
             task_id)
        )

        full_text = _read_full_text(result['save_path']) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''),
                   full_text, title=result.get('title'))
        conn.commit()
        conn.close()
        success(f'[Weibo Task {task_id}] Saved: {result.get("author_name", url)}')

    except Exception as e:
        error(f'[Weibo Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='weibo save')
        except Exception:
            pass


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
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''), full_text,
                   title=_read_title(result['save_path']))
        conn.commit()
        conn.close()
        success(f'[XHS Task {task_id}] Saved: {result["title"]}')
    except Exception as e:
        error(f'[XHS Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='xhs save')
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
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''), full_text,
                   title=_read_title(result.get('save_path', '')))
        conn.commit()
        conn.close()
        success(f'[WeChat Task {task_id}] Saved: {result["title"]}')
    except Exception as e:
        error(f'[WeChat Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='wechat save')
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
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''), full_text,
                   title=_read_title(result['save_path']))
        conn.commit()
        conn.close()
        success(f'[YouTube Task {task_id}] Saved: {result["title"]}')
    except Exception as e:
        error(f'[YouTube Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='youtube save')
        except Exception:
            pass


def process_douyin_task(task_id: int, url: str):
    """Queue worker handler for Douyin/TikTok tasks."""
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        svc = make_douyin_service()
        result = svc.save_video(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?,
               author_username=?, author_name=?, save_path=?, tweet_text=?,
               share_slug=?, media_count=?, content_type='douyin' WHERE id=?''',
            (now, result['video_id'],
             result.get('author_username', ''), result.get('author_name', ''),
             result['save_path'], result.get('tweet_text', '')[:500],
             slug, result.get('media_count', 1),
             task_id)
        )
        full_text = _read_full_text(result['save_path']) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''),
                   full_text, title=_read_title(result['save_path']))
        conn.commit()
        conn.close()
        success(f'[Douyin Task {task_id}] Saved: {result.get("title", url)}')

    except Exception as e:
        error(f'[Douyin Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='douyin save')
        except Exception:
            pass


def process_webpage_task(task_id: int, url: str):
    """Queue worker handler for generic web page tasks."""
    from services.zhihu_service import ZhihuService

    zhihu_type = ZhihuService.classify_zhihu_url(url)
    if zhihu_type:
        normalized_url = ZhihuService.normalize_zhihu_url(url)
        if normalized_url != url:
            conn = get_db_connection()
            try:
                conn.execute('UPDATE tasks SET url=? WHERE id=?', (normalized_url, task_id))
                conn.commit()
            finally:
                conn.close()
        info(f'[Webpage Task {task_id}] Detected Zhihu {zhihu_type} URL, rerouting to Zhihu service: {normalized_url}')
        process_zhihu_task(task_id, normalized_url)
        return

    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        svc = make_webpage_service()
        result = svc.save_page(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?,
               author_username=?, author_name=?, save_path=?, tweet_text=?,
               share_slug=?, media_count=?, content_type='webpage' WHERE id=?''',
            (now, result.get('page_id', ''),
             result.get('author_username', ''), result.get('author_name', ''),
             result.get('save_path', ''), result.get('tweet_text', '')[:500],
             slug, result.get('image_count', 0),
             task_id)
        )
        full_text = _read_full_text(result.get('save_path', '')) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''), full_text,
                   title=_read_title(result.get('save_path', '')))
        conn.commit()
        conn.close()
        success(f'[Webpage Task {task_id}] Saved: {result["title"]}')
    except Exception as e:
        error(f'[Webpage Task {task_id}] Failed: {e}')
        try:
            _store_task_failure(task_id, e, url=url, stage='webpage save')
        except Exception:
            pass


def process_tweet_task(task_id, url):
    """处理单个推文任务"""
    from datetime import datetime
    from services.twitter_service import TwitterScrapingError
    from utils.url_parser import TwitterURLParser

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
        tweet_id = _twitter_service.extract_tweet_id(url)
        info(f"[Task {task_id}] Extracted tweet ID: {tweet_id}")

        # 获取推文数据
        try:
            info(f"[Task {task_id}] Calling Twitter service to get tweet...")
            update_task_progress(task_id, 'api_call', f'正在获取推文 {tweet_id}')

            # 检测是否为长文
            is_article = TwitterURLParser.is_article_url(url)
            content_type = 'article' if is_article else 'tweet'
            if is_article:
                info(f"[Task {task_id}] Detected article URL, will scrape full article content")
                update_task_progress(task_id, 'article_detected', '检测到长文链接，将抓取长文内容')

            # 当 xreach 可用时，直接抓完整串推；否则只抓单条
            if not is_article and _twitter_service.use_xreach:
                update_task_progress(task_id, 'api_call', f'正在获取串推 {tweet_id}（xreach）')
                tweets = _twitter_service.get_thread_by_url(url)
                is_thread = len(tweets) > 1
                success(f"[Task {task_id}] Got {len(tweets)} tweet(s) from @{tweets[0].author_username}")
                update_task_progress(task_id, 'api_success', f'成功获取 {len(tweets)} 条推文，作者: @{tweets[0].author_username}')
            else:
                update_task_progress(task_id, 'api_call', f'正在获取推文 {tweet_id}')
                single_tweet = _twitter_service.get_tweet(url)
                success(f"[Task {task_id}] Successfully got tweet from @{single_tweet.author_username}")
                update_task_progress(task_id, 'api_success', f'成功获取推文，作者: @{single_tweet.author_username}')
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
        save_dir = _file_manager.create_save_directory(tweets[0].id, tweets[0].created_at)
        update_task_progress(task_id, 'saving', f'创建保存目录: {save_dir}')

        # 收集所有推文的媒体，按推文分组跟踪以便后续关联
        all_images_flat = []
        all_videos_flat = []
        all_avatars_flat = []
        tweet_img_ranges = []   # (start, end) index in all_images_flat per tweet
        tweet_vid_ranges = []
        for tweet in tweets:
            i0 = len(all_images_flat); all_images_flat.extend(tweet.get_images()); tweet_img_ranges.append((i0, len(all_images_flat)))
            v0 = len(all_videos_flat); all_videos_flat.extend(tweet.get_videos()); tweet_vid_ranges.append((v0, len(all_videos_flat)))
            all_avatars_flat.extend(tweet.get_avatars())

        total_images = len(all_images_flat)
        total_videos = len(all_videos_flat)
        total_media = total_images + total_videos + len(all_avatars_flat)

        if total_media > 0:
            update_task_progress(task_id, 'media_download', f'准备下载 {total_media} 个媒体文件 (图片:{total_images}, 视频:{total_videos})')

        # 批量下载 — 全局连续命名，避免多条推文同扩展名互相覆盖
        all_media_files = []
        downloaded_count = 0

        if all_images_flat:
            update_task_progress(task_id, 'downloading_images', f'正在下载图片 ({total_images} 个)...')
            image_files = _media_downloader.download_images(all_images_flat, save_dir)
            all_media_files.extend(image_files)
            downloaded_count += len(image_files)
            update_task_progress(task_id, 'images_done', f'图片下载完成 ({len(image_files)}/{total_images})')
        else:
            image_files = []

        if all_videos_flat:
            update_task_progress(task_id, 'downloading_videos', f'正在下载视频 ({total_videos} 个)...')
            video_files = _media_downloader.download_videos(all_videos_flat, save_dir)
            all_media_files.extend(video_files)
            downloaded_count += len(video_files)
            update_task_progress(task_id, 'videos_done', f'视频下载完成 ({len(video_files)}/{total_videos})')
        else:
            video_files = []

        if all_avatars_flat:
            update_task_progress(task_id, 'downloading_avatars', f'正在下载头像...')
            avatar_files = _media_downloader.download_avatars(all_avatars_flat, save_dir)
            all_media_files.extend(avatar_files)
            downloaded_count += len(avatar_files)

        # 建立 per-tweet 媒体映射（传给 save_thread_content 用于生成带图 HTML）
        tweet_media_map = []
        for i in range(len(tweets)):
            i0, i1 = tweet_img_ranges[i]
            v0, v1 = tweet_vid_ranges[i]
            tweet_media_map.append(image_files[i0:i1] + video_files[v0:v1])

        if total_media > 0:
            update_task_progress(task_id, 'media_complete', f'媒体下载完成: {downloaded_count}/{total_media} 个文件')

        # 保存推文内容
        # Use save_tweet_content only when html_content is available (Playwright scraping).
        # For xreach tweets (html_content=None), always use save_thread_content so
        # content.html is generated with inline media regardless of tweet count.
        if len(tweets) == 1 and tweets[0].html_content is not None:
            _file_manager.save_tweet_content(tweets[0], save_dir, all_media_files)
        else:
            _file_manager.save_thread_content(tweets, save_dir, all_media_files, tweet_media_map=tweet_media_map)

        # 保存元数据
        _file_manager.save_metadata(tweets, save_dir, all_media_files)

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
        fts_upsert(conn, task_id, tweets[0].author_name, tweets[0].author_username, full_text,
                   title=_read_title(save_dir))
        conn.commit()

        info(f"[Task {task_id}] Generated share slug: {share_slug}")

    except Exception as e:
        # 检查是否应该重试
        error_details = _build_task_error_details(e, task_id=task_id, url=url, stage='tweet save')
        should_retry = check_and_schedule_retry(conn.cursor(), task_id, str(e), error_details=error_details)
        if not should_retry:
            # 不重试，更新任务状态为失败
            conn.execute(
                'UPDATE tasks SET status = ?, error_message = ? WHERE id = ?',
                ('failed', error_details, task_id)
            )
        conn.commit()

    finally:
        conn.close()


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


def queue_processor():
    """队列处理器"""
    global is_processing

    info("[Queue Processor] Starting queue processor thread...")

    while True:
        try:
            # 检查是否有待重试的任务
            check_retry_ready_tasks()

            # 检查是否有pending任务需要加入队列（每30秒检查一次）
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
                elif _content_type == 'zhihu':
                    process_zhihu_task(task_id, url)
                elif _content_type == 'wechat':
                    process_wechat_task(task_id, url)
                elif _content_type == 'youtube':
                    process_youtube_task(task_id, url)
                elif _content_type == 'douyin':
                    process_douyin_task(task_id, url)
                elif _content_type == 'weibo':
                    process_weibo_task(task_id, url)
                elif _content_type == 'bilibili':
                    process_bilibili_task(task_id, url)
                elif _content_type == 'kuaishou':
                    process_kuaishou_task(task_id, url)
                elif _content_type == 'instagram':
                    process_instagram_task(task_id, url)
                elif _content_type == 'pinterest':
                    process_pinterest_task(task_id, url)
                elif _content_type == 'reddit':
                    process_reddit_task(task_id, url)
                elif _content_type == 'webpage':
                    process_webpage_task(task_id, url)
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


def task_monitor():
    """任务监控器，定期检查卡住的任务"""
    info("[Task Monitor] Starting task monitor thread")

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
                warning(f"[Task Monitor] Found {len(stuck_tasks)} stuck tasks, recovering")

                for task in stuck_tasks:
                    warning(f"[Task Monitor] Recovering stuck task {task['id']}")
                    # 重置为pending状态
                    conn.execute(
                        'UPDATE tasks SET status = ?, error_message = ? WHERE id = ?',
                        ('pending', 'Task recovered from stuck state', task['id'])
                    )
                    # 重新加入队列
                    enqueue_task(task['id'], task['url'])

                conn.commit()
                success(f"[Task Monitor] Recovered {len(stuck_tasks)} stuck tasks")

            conn.close()

        except Exception as e:
            error(f"[Task Monitor] Error in task monitor: {e}")


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


def auto_fix_stuck_tasks():
    """自动修复卡住的任务"""
    try:
        conn = get_db_connection()

        # 检查是否有卡住的processing任务
        stuck_tasks = conn.execute(
            'SELECT id, url FROM tasks WHERE status = "processing"'
        ).fetchall()

        if stuck_tasks:
            warning(f"[Auto Fix] Found {len(stuck_tasks)} stuck tasks, auto-fixing")

            # 重置为pending
            conn.execute('UPDATE tasks SET status = "pending" WHERE status = "processing"')
            conn.commit()

            # 重新加入队列
            for task in stuck_tasks:
                enqueue_task(task['id'], task['url'])
                info(f"[Auto Fix] Requeued task {task['id']}")

            success(f"[Auto Fix] Auto-fixed {len(stuck_tasks)} stuck tasks")

        conn.close()

    except Exception as e:
        error(f"[Auto Fix] Error in auto fix: {e}")


def load_pending_tasks():
    """加载数据库中的待处理任务到队列"""
    conn = get_db_connection()

    # 首先，将所有processing状态的任务重置为pending（可能是之前异常退出导致的）
    processing_tasks = conn.execute(
        'SELECT id FROM tasks WHERE status = "processing"'
    ).fetchall()

    if processing_tasks:
        warning(f"[Startup] Found {len(processing_tasks)} stuck processing tasks, resetting to pending")
        conn.execute('UPDATE tasks SET status = "pending" WHERE status = "processing"')
        conn.commit()
        success(f"[Startup] Reset {len(processing_tasks)} stuck tasks to pending")

    # 加载所有pending任务到队列
    pending_tasks = conn.execute(
        'SELECT id, url FROM tasks WHERE status = "pending" ORDER BY created_at ASC'
    ).fetchall()

    for task in pending_tasks:
        if enqueue_task(task['id'], task['url']):
            info(f"[Startup] Loaded pending task {task['id']} into queue")

    conn.close()

    if pending_tasks:
        info(f"[Startup] Loaded {len(pending_tasks)} pending tasks into queue")
    else:
        info("[Startup] No pending tasks found")


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

import os
import sqlite3
import secrets
import json
from datetime import datetime, timedelta, timezone

DATA_DIR = os.environ.get(
    'DATA_DIR',
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


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

    # Multi-key API authentication table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT '',
            key TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Migrate legacy single api_key if present and table is empty
    legacy = cursor.execute(
        "SELECT value FROM app_settings WHERE key = 'api_key'"
    ).fetchone()
    if legacy and legacy[0]:
        cursor.execute(
            "INSERT OR IGNORE INTO api_keys (name, key) VALUES (?, ?)",
            ('Default', legacy[0])
        )

    # FTS5 full-text search table (trigram tokenizer for CJK substring matching)
    # Recreate if schema changed (e.g. added trigram, switched to content-storing)
    _fts_exists = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks_fts'"
    ).fetchone()
    _fts_sql = _fts_exists[0] if _fts_exists else ''
    _need_recreate = _fts_exists and (
        "content=''" in _fts_sql or
        'trigram' not in _fts_sql or
        'title' not in _fts_sql
    )
    if _need_recreate:
        cursor.execute('DROP TABLE IF EXISTS tasks_fts')
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
            title,
            author_name,
            author_username,
            full_text,
            content_rowid='id',
            tokenize='trigram'
        )
    ''')

    conn.commit()
    conn.close()


def fts_upsert(conn, task_id, author_name, author_username, full_text, title=''):
    """Insert or replace a row in the FTS5 index."""
    # Delete old entry if exists, then insert new one
    conn.execute('DELETE FROM tasks_fts WHERE rowid = ?', (task_id,))
    conn.execute(
        'INSERT INTO tasks_fts(rowid, title, author_name, author_username, full_text) VALUES(?, ?, ?, ?, ?)',
        (task_id, title or '', author_name or '', author_username or '', full_text or '')
    )


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


def _read_title(save_path):
    """Read title from metadata.json for FTS indexing."""
    if not save_path:
        return ''
    meta_path = os.path.join(save_path, 'metadata.json')
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding='utf-8') as f:
                meta = json.loads(f.read())
            return (meta.get('title') or '').strip()
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
        title = _read_title(t['save_path'])
        if full_text or title:
            conn.execute(
                'INSERT INTO tasks_fts(rowid, title, author_name, author_username, full_text) VALUES(?, ?, ?, ?, ?)',
                (t['id'], title, t['author_name'] or '', t['author_username'] or '', full_text)
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

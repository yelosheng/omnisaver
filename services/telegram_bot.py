"""Telegram Bot Service for Twitter Saver

First user to send /start becomes the permanent owner.
Owner can send or forward any message containing a Twitter/X URL to save it.
"""

import asyncio
import json
import logging
import os
import re
import threading
from datetime import datetime
from typing import Optional, Callable

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)

logger = logging.getLogger(__name__)

OWNER_FILE = os.path.join(os.environ.get('DATA_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'telegram_owner.json')

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
_bot_thread: Optional[threading.Thread] = None
_bot_running: bool = False
_bot_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Owner persistence
# ---------------------------------------------------------------------------

def load_owner() -> Optional[dict]:
    if not os.path.exists(OWNER_FILE):
        return None
    try:
        with open(OWNER_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def save_owner(user_id: int, username: str, first_name: str = '') -> None:
    with open(OWNER_FILE, 'w') as f:
        json.dump({
            'user_id': user_id,
            'username': username or first_name or str(user_id),
            'registered_at': datetime.now().isoformat()
        }, f, indent=2)


def clear_owner() -> None:
    if os.path.exists(OWNER_FILE):
        os.remove(OWNER_FILE)


# ---------------------------------------------------------------------------
# Public status API (called by Flask routes)
# ---------------------------------------------------------------------------

def get_status() -> dict:
    return {
        'running': _bot_running,
        'error': _bot_error,
        'owner': load_owner(),
    }


# ---------------------------------------------------------------------------
# URL extraction
# ---------------------------------------------------------------------------

_TWEET_URL_RE = re.compile(
    r'https?://(?:www\.|mobile\.|m\.)?(?:twitter\.com|x\.com)/\w+/status/\d+'
)

_XHS_URL_RE = re.compile(
    r'https?://(?:xhslink\.com|(?:www\.)?xiaohongshu\.com/explore/[a-f0-9]+)[^\s]*'
)

_WECHAT_URL_RE = re.compile(
    r'https?://mp\.weixin\.qq\.com/s[/\?][^\s]+'
)

_YOUTUBE_URL_RE = re.compile(
    r'https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/)|youtu\.be/)'
    r'[A-Za-z0-9_-]{11}'
)


def _extract_twitter_url(text: str) -> Optional[str]:
    m = _TWEET_URL_RE.search(text)
    return m.group(0) if m else None


def _extract_xhs_url(text: str) -> Optional[str]:
    m = _XHS_URL_RE.search(text)
    return m.group(0) if m else None


def _extract_wechat_url(text: str) -> Optional[str]:
    m = _WECHAT_URL_RE.search(text)
    return m.group(0) if m else None


def _extract_youtube_url(text: str) -> Optional[str]:
    m = _YOUTUBE_URL_RE.search(text)
    return m.group(0) if m else None


def _extract_any_url(text: str) -> Optional[str]:
    """Extract the first http/https URL from text."""
    import re as _re
    m = _re.search(r'https?://\S+', text)
    return m.group(0).rstrip('.,)>»') if m else None


# ---------------------------------------------------------------------------
# Handlers (closures over submit_callback)
# ---------------------------------------------------------------------------

def _make_handlers(submit_callback: Callable):

    async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        owner = load_owner()
        if owner is None:
            save_owner(user.id, user.username or '', user.first_name or '')
            await update.message.reply_text(
                f"👋 Hi {user.first_name}! You are now the owner of this bot.\n"
                "Send or forward any tweet link to save it.\n\n"
                "/status — show queue info"
            )
        elif owner['user_id'] == user.id:
            await update.message.reply_text(
                "👋 Welcome back! Send me a Twitter/X URL to save it.\n"
                "/status — show queue info"
            )
        # Non-owner: silently ignore

    async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        owner = load_owner()
        if owner is None or owner['user_id'] != update.effective_user.id:
            return
        # Deferred import — safe since app.py is fully loaded before bot starts
        from app import processing_queue
        queue_size = processing_queue.qsize()
        await update.message.reply_text(
            f"📊 Queue: {queue_size} pending task(s)\n"
            "Full details at the web UI."
        )

    async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        owner = load_owner()
        if owner is None or owner['user_id'] != update.effective_user.id:
            return

        text = (update.message.text or update.message.caption or '').strip()

        # XiaoHongShu URL
        xhs_url = _extract_xhs_url(text)
        if xhs_url:
            try:
                from services.xhs_service import XHSService
                from app import processing_queue, get_db_connection, format_time_for_db, get_current_time
                xhs_url = XHSService.resolve_xhslink(xhs_url)
                xhs_url = XHSService.normalize_xhs_url(xhs_url)
                if not XHSService.is_valid_xhs_url(xhs_url):
                    await update.message.reply_text("❌ Invalid XiaoHongShu URL.")
                    return
                conn = get_db_connection()
                existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (xhs_url,)).fetchone()
                if existing:
                    conn.close()
                    await update.message.reply_text(
                        f"⚠️ Already queued/saved (task #{existing['id']}, status: {existing['status']})"
                    )
                else:
                    import sqlite3 as _sq
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, 'xhs')",
                        (xhs_url, format_time_for_db(get_current_time()))
                    )
                    task_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    processing_queue.put((task_id, xhs_url))
                    await update.message.reply_text(f"✅ Added to queue (task #{task_id})")
            except Exception as e:
                await update.message.reply_text(f"❌ XHS submit failed: {e}")
            return

        # WeChat 公众号 URL
        wechat_url = _extract_wechat_url(text)
        if wechat_url:
            try:
                from services.wechat_service import WechatService
                from app import processing_queue, get_db_connection, format_time_for_db, get_current_time
                if not WechatService.is_valid_wechat_url(wechat_url):
                    await update.message.reply_text("❌ Invalid WeChat URL.")
                    return
                conn = get_db_connection()
                existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (wechat_url,)).fetchone()
                if existing:
                    conn.close()
                    await update.message.reply_text(
                        f"⚠️ Already queued/saved (task #{existing['id']}, status: {existing['status']})"
                    )
                else:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, 'wechat')",
                        (wechat_url, format_time_for_db(get_current_time()))
                    )
                    task_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    processing_queue.put((task_id, wechat_url))
                    await update.message.reply_text(f"✅ Added to queue (task #{task_id})")
            except Exception as e:
                await update.message.reply_text(f"❌ WeChat submit failed: {e}")
            return

        # YouTube URL
        youtube_url = _extract_youtube_url(text)
        if youtube_url:
            try:
                from services.youtube_service import YoutubeService
                from app import processing_queue, get_db_connection, format_time_for_db, get_current_time
                youtube_url = YoutubeService.normalize_url(youtube_url)
                conn = get_db_connection()
                existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (youtube_url,)).fetchone()
                if existing:
                    conn.close()
                    await update.message.reply_text(
                        f"⚠️ Already queued/saved (task #{existing['id']}, status: {existing['status']})"
                    )
                else:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, 'youtube')",
                        (youtube_url, format_time_for_db(get_current_time()))
                    )
                    task_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    processing_queue.put((task_id, youtube_url))
                    await update.message.reply_text(f"✅ Added to queue (task #{task_id})")
            except Exception as e:
                await update.message.reply_text(f"❌ YouTube submit failed: {e}")
            return

        # Douyin / TikTok URL
        from services.douyin_service import DouyinService
        douyin_url = DouyinService.extract_url_from_share_text(text)
        if douyin_url:
            try:
                from app import processing_queue, get_db_connection, format_time_for_db, get_current_time
                conn = get_db_connection()
                existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (douyin_url,)).fetchone()
                if existing:
                    conn.close()
                    await update.message.reply_text(
                        f"⚠️ Already queued/saved (task #{existing['id']}, status: {existing['status']})"
                    )
                else:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, 'douyin')",
                        (douyin_url, format_time_for_db(get_current_time()))
                    )
                    task_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    processing_queue.put((task_id, douyin_url))
                    await update.message.reply_text(f"✅ Added to queue (task #{task_id})")
            except Exception as e:
                await update.message.reply_text(f"❌ Douyin submit failed: {e}")
            return

        # Weibo URL
        from services.weibo_service import WeiboService
        weibo_url = WeiboService.extract_url_from_share_text(text)
        if weibo_url:
            try:
                from app import processing_queue, get_db_connection, format_time_for_db, get_current_time
                conn = get_db_connection()
                existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (weibo_url,)).fetchone()
                if existing:
                    conn.close()
                    await update.message.reply_text(
                        f"⚠️ Already queued/saved (task #{existing['id']}, status: {existing['status']})"
                    )
                else:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, 'weibo')",
                        (weibo_url, format_time_for_db(get_current_time()))
                    )
                    task_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    processing_queue.put((task_id, weibo_url))
                    await update.message.reply_text(f"✅ Added to queue (task #{task_id})")
            except Exception as e:
                await update.message.reply_text(f"❌ Weibo submit failed: {e}")
            return

        # Kuaishou URL
        from services.kuaishou_service import KuaishouService
        kuaishou_url = KuaishouService.extract_url_from_share_text(text)
        if kuaishou_url:
            try:
                from app import processing_queue, get_db_connection, format_time_for_db, get_current_time
                conn = get_db_connection()
                existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (kuaishou_url,)).fetchone()
                if existing:
                    conn.close()
                    await update.message.reply_text(
                        f"⚠️ Already queued/saved (task #{existing['id']}, status: {existing['status']})"
                    )
                else:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, 'kuaishou')",
                        (kuaishou_url, format_time_for_db(get_current_time()))
                    )
                    task_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    processing_queue.put((task_id, kuaishou_url))
                    await update.message.reply_text(f"✅ Added to queue (task #{task_id})")
            except Exception as e:
                await update.message.reply_text(f"❌ Kuaishou submit failed: {e}")
            return

        # Bilibili URL
        from services.bilibili_service import BilibiliService
        bilibili_url = BilibiliService.extract_url_from_share_text(text)
        if bilibili_url:
            try:
                from app import processing_queue, get_db_connection, format_time_for_db, get_current_time
                conn = get_db_connection()
                existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (bilibili_url,)).fetchone()
                if existing:
                    conn.close()
                    await update.message.reply_text(
                        f"⚠️ Already queued/saved (task #{existing['id']}, status: {existing['status']})"
                    )
                else:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, 'bilibili')",
                        (bilibili_url, format_time_for_db(get_current_time()))
                    )
                    task_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    processing_queue.put((task_id, bilibili_url))
                    await update.message.reply_text(f"✅ Added to queue (task #{task_id})")
            except Exception as e:
                await update.message.reply_text(f"❌ Bilibili submit failed: {e}")
            return

        # Twitter/X URL
        url = _extract_twitter_url(text)
        if not url:
            # Generic webpage fallback — any http/https URL
            from services.webpage_service import WebpageService
            webpage_url = _extract_any_url(text)
            if webpage_url and WebpageService.is_valid_webpage_url(webpage_url):
                try:
                    from app import processing_queue, get_db_connection, format_time_for_db, get_current_time
                    conn = get_db_connection()
                    existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (webpage_url,)).fetchone()
                    if existing:
                        conn.close()
                        await update.message.reply_text(
                            f"⚠️ Already queued/saved (task #{existing['id']}, status: {existing['status']})"
                        )
                    else:
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, 'webpage')",
                            (webpage_url, format_time_for_db(get_current_time()))
                        )
                        task_id = cursor.lastrowid
                        conn.commit()
                        conn.close()
                        processing_queue.put((task_id, webpage_url))
                        await update.message.reply_text(f"✅ Added to queue (task #{task_id})")
                except Exception as e:
                    await update.message.reply_text(f"❌ Webpage submit failed: {e}")
                return
            await update.message.reply_text(
                "❌ No supported URL found. Supports: Twitter/X, XiaoHongShu, WeChat, YouTube, Douyin/TikTok, Weibo, Bilibili, Kuaishou, or any webpage URL."
            )
            return

        result = submit_callback(url)
        if not result.get('success'):
            await update.message.reply_text("❌ Invalid URL.")
        elif result.get('duplicate'):
            await update.message.reply_text(
                f"⚠️ Already saved (task #{result['task_id']}, status: {result['status']})"
            )
        else:
            await update.message.reply_text(
                f"✅ Added to queue (task #{result['task_id']})"
            )

    return start_handler, status_handler, message_handler


# ---------------------------------------------------------------------------
# Bot runner
# ---------------------------------------------------------------------------

_AVATAR_PATH = os.path.join(os.path.dirname(__file__), '..', 'telegram_avatar.png')


async def _post_init(application: Application) -> None:
    avatar = os.path.normpath(_AVATAR_PATH)
    if os.path.exists(avatar):
        try:
            with open(avatar, 'rb') as f:
                await application.bot.set_my_photo(photo=f)
            logger.info("Telegram bot avatar set")
        except Exception as e:
            logger.warning(f"Could not set bot avatar: {e}")


def _run_in_thread(token: str, submit_callback: Callable) -> None:
    global _bot_running, _bot_error
    _bot_running = True
    _bot_error = None
    try:
        start_h, status_h, message_h = _make_handlers(submit_callback)
        application = Application.builder().token(token).post_init(_post_init).build()
        application.add_handler(CommandHandler('start', start_h))
        application.add_handler(CommandHandler('status', status_h))
        application.add_handler(
            MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, message_h)
        )
        # stop_signals=None required when running in a non-main thread
        application.run_polling(stop_signals=None)
    except Exception as e:
        logger.error(f"Telegram bot error: {e}")
        _bot_error = str(e)
    finally:
        _bot_running = False


def start_bot(token: str, submit_callback: Callable) -> None:
    """Start the bot in a daemon thread. No-op if already running."""
    global _bot_thread
    if _bot_running and _bot_thread and _bot_thread.is_alive():
        logger.info("Telegram bot already running, skipping start")
        return
    _bot_thread = threading.Thread(
        target=_run_in_thread,
        args=(token, submit_callback),
        daemon=True,
        name='telegram-bot',
    )
    _bot_thread.start()
    logger.info("Telegram bot thread started")

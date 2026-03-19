#!/usr/bin/env python3
"""
Twitter Content Saver Tool - Web Application Startup Script
"""

import os
import sys
import webbrowser
import time
import threading
import logging
from app import app, init_db, init_services, start_background_thread, load_pending_tasks, start_xhs_autosave, get_setting, get_db_connection, rebuild_fts_index


def open_browser():
    """Delayed browser opening"""
    time.sleep(1.5)
    webbrowser.open('http://localhost:6201')

def main():
    """Main function"""
    # 强制刷新输出缓冲区 - 修复SSH环境下日志不显示的问题
    import sys
    sys.stdout.flush()
    sys.stderr.flush()
    
    # 配置日志级别，减少HTTP请求日志
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
    # 配置基础日志格式，确保在SSH环境下也能正常显示
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        stream=sys.stdout
    )
    
    print("=" * 60)
    print("Twitter Content Saver Tool - Web Version")
    print("=" * 60)
    sys.stdout.flush()  # 立即刷新输出
    
    
    # Configure session security settings
    app.config['SESSION_COOKIE_NAME'] = 'twitter_saver_session'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False
    print("HTTP mode enabled")
    
    # Check configuration
    print("Checking configuration...")
    if not os.path.exists('config.ini'):
        print("Warning: config.ini not found, using default settings")
        print("The application will use default save path: /mnt/nas/saved_tweets")
        print("You can create config.ini to customize settings (see README.md)")
    
    # Initialize database
    print("Initializing database...")
    try:
        init_db()
        print("Database initialization complete")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        sys.exit(1)

    # Build FTS index if empty
    try:
        _fts_conn = get_db_connection()
        _fts_count = _fts_conn.execute("SELECT COUNT(*) FROM tasks_fts").fetchone()[0]
        _tasks_count = _fts_conn.execute("SELECT COUNT(*) FROM tasks WHERE status='completed'").fetchone()[0]
        _fts_conn.close()
        if _fts_count == 0 and _tasks_count > 0:
            print(f"[FTS] Index empty, rebuilding from {_tasks_count} completed tasks...")
            n = rebuild_fts_index()
            print(f"[FTS] Indexed {n} entries.")
        else:
            print(f"[FTS] Index OK ({_fts_count} entries)")
    except Exception as e:
        print(f"[FTS] Warning: {e}")

    # Initialize services
    print("Initializing services...")
    if not init_services():
        print("Service initialization failed, please check configuration")
        sys.exit(1)
    print("Service initialization complete")
    
    # Start background processing thread
    print("Starting background processing...")
    try:
        start_background_thread()
        print("Background processing started")
    except Exception as e:
        print(f"Failed to start background processing: {e}")
        sys.exit(1)
    
    # Start Telegram bot if configured
    print("Starting Telegram bot...")
    try:
        import configparser as cp
        _cfg = cp.ConfigParser()
        if os.path.exists('config.ini'):
            _cfg.read('config.ini')
        _tg_token = _cfg.get('telegram', 'bot_token', fallback='').strip()
        if _tg_token:
            from services.telegram_bot import start_bot
            from app import _telegram_submit
            start_bot(_tg_token, _telegram_submit)
            print("Telegram bot started")
        else:
            print("Telegram bot not configured (add bot_token to config.ini [telegram])")
    except Exception as e:
        print(f"Telegram bot startup failed (non-fatal): {e}")

    # Start XHS auto-save if enabled
    try:
        if get_setting('xhs_autosave_enabled', 'false') == 'true':
            start_xhs_autosave()
            print("XHS auto-save started")
        else:
            print("XHS auto-save not enabled (configure at /xhs)")
    except Exception as e:
        print(f"XHS auto-save startup failed (non-fatal): {e}")

    # Load pending tasks
    print("Loading pending tasks...")
    try:
        load_pending_tasks()
        print("Pending tasks loaded")
    except Exception as e:
        print(f"Failed to load pending tasks: {e}")
        # 不退出，因为这不是致命错误
    
    # Start browser
    if '--no-browser' not in sys.argv:
        browser_thread = threading.Thread(target=open_browser)
        browser_thread.daemon = True
        browser_thread.start()
    
    print(f"\nWeb application starting...")
    print(f"Access URL: http://localhost:6201")
    print("Press Ctrl+C to stop service")
    print("=" * 60)
    
    try:
        # Start Flask application
        # 禁用输出缓冲以确保日志实时显示
        os.environ['PYTHONUNBUFFERED'] = '1'

        app.run(
            debug=False,
            host='0.0.0.0',
            port=6201,
            use_reloader=False,
            threaded=True  # 启用多线程模式以提高性能
        )
    except KeyboardInterrupt:
        print("\n\nService stopped")
    except Exception as e:
        print(f"\nService startup failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
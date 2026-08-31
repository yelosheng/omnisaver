#!/usr/bin/env python3
"""
yt-dlp 工具模块
提供统一的 yt-dlp 执行、版本过旧与 403 错误检测、自动热升级与自愈重试能力。
"""

import os
import sys
import time
import shutil
import threading
import subprocess
from pathlib import Path
from typing import List, Optional

from utils.realtime_logger import info, warning, success, error

_EXTRA_PATH_DIRS = [
    os.path.dirname(sys.executable),
    os.path.expanduser('~/.pyenv/shims'),
    os.path.expanduser('~/.pyenv/versions/3.11.9/bin'),
    os.path.expanduser('~/.npm-global/bin'),
]

_UPGRADE_LOCK = threading.Lock()
_LAST_UPGRADE_TIME = 0.0
_UPGRADE_COOLDOWN_SECONDS = 600  # 10分钟内最多自动触发一次升级


def ensure_ytdlp_path():
    """确保 yt-dlp 所在路径已添加到环境变量 PATH 中。"""
    current_path = os.environ.get('PATH', '')
    for p in _EXTRA_PATH_DIRS:
        if p and os.path.exists(p) and p not in current_path:
            current_path = f"{p}:{current_path}"
    os.environ['PATH'] = current_path


# 初始化时注入 PATH
ensure_ytdlp_path()


def is_ytdlp_outdated_error(text: str) -> bool:
    """
    检查错误文本是否表明 yt-dlp 版本过老或媒体流签名失效 (如 403 Forbidden / n-sig 提取失败)。
    """
    if not text:
        return False
    lowered = text.lower()
    patterns = [
        'older than 90 days',
        'older than 30 days',
        'http error 403',
        '403: forbidden',
        'unable to download video data',
        'sign in to confirm you’re not a bot',
        'sign in to confirm you are not a bot',
        'signature extraction failed',
        'n challenge',
        'nsig extraction failed',
        'extractornothing',
        'requested format is not available',
    ]
    return any(p in lowered for p in patterns)


def upgrade_ytdlp(force: bool = False) -> bool:
    """
    尝试升级系统中的 yt-dlp。
    使用线程锁和冷却时间，避免并发重复升级。
    """
    global _LAST_UPGRADE_TIME
    with _UPGRADE_LOCK:
        now = time.time()
        if not force and (now - _LAST_UPGRADE_TIME) < _UPGRADE_COOLDOWN_SECONDS:
            info(f"[yt-dlp] 升级冷却中（上次升级在 {int(now - _LAST_UPGRADE_TIME)} 秒前），跳过本次重复升级")
            return True

        info("[yt-dlp] 检测到版本过旧或流签名失效，正在自动升级 yt-dlp...")
        upgraded_any = False

        # 1. 升级当前 Python 环境中的 yt-dlp
        pip_cmds = [
            [sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp']
        ]

        # 2. 如果存在 pyenv pip，也一并升级
        pyenv_pip = os.path.expanduser('~/.pyenv/shims/pip')
        if os.path.exists(pyenv_pip) and pyenv_pip != sys.executable:
            pip_cmds.append([pyenv_pip, 'install', '--upgrade', 'yt-dlp'])

        for cmd in pip_cmds:
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if res.returncode == 0:
                    upgraded_any = True
                else:
                    warning(f"[yt-dlp] 命令 {' '.join(cmd)} 升级失败: {res.stderr.strip()[:200]}")
            except Exception as e:
                warning(f"[yt-dlp] 执行升级异常: {e}")

        if upgraded_any:
            _LAST_UPGRADE_TIME = now
            # 获取最新版本号
            try:
                ver_res = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True, timeout=10)
                ver_str = ver_res.stdout.strip() if ver_res.returncode == 0 else "未知"
                success(f"[yt-dlp] ✓ yt-dlp 自动升级完成！当前版本: {ver_str}")
            except Exception:
                success("[yt-dlp] ✓ yt-dlp 自动升级成功完成！")
            return True
        else:
            error("[yt-dlp] ✗ yt-dlp 自动升级失败")
            return False


def run_ytdlp(
    cmd: List[str],
    auto_retry_on_upgrade: bool = True,
    err_log_path: Optional[str] = None,
    **subprocess_kwargs
) -> subprocess.CompletedProcess:
    """
    包装执行 yt-dlp 命令。
    如果执行失败且检测到版本过老/403 等流签名错误，自动升级 yt-dlp 并重试一次。
    """
    ensure_ytdlp_path()

    # 首次执行
    result = subprocess.run(cmd, **subprocess_kwargs)

    if result.returncode == 0 or not auto_retry_on_upgrade:
        return result

    # 收集错误输出
    err_text = ""
    if result.stderr:
        if isinstance(result.stderr, bytes):
            err_text += result.stderr.decode('utf-8', errors='replace')
        else:
            err_text += str(result.stderr)
    if result.stdout:
        if isinstance(result.stdout, bytes):
            err_text += " " + result.stdout.decode('utf-8', errors='replace')
        else:
            err_text += " " + str(result.stdout)
    if err_log_path and os.path.exists(err_log_path):
        try:
            err_text += " " + Path(err_log_path).read_text(encoding='utf-8', errors='replace')
        except Exception:
            pass

    if is_ytdlp_outdated_error(err_text):
        warning(f"[yt-dlp] 命中流签名/版本过旧错误特征，触发自动升级与自愈重试...")
        if upgrade_ytdlp(force=False):
            info(f"[yt-dlp] 正在重新执行下载命令: {' '.join(cmd[:3])} ...")
            # 重新执行
            retry_result = subprocess.run(cmd, **subprocess_kwargs)
            if retry_result.returncode == 0:
                success(f"[yt-dlp] ✓ 自愈成功：升级后重新执行成功！")
            return retry_result

    return result


_periodic_thread: Optional[threading.Thread] = None
_periodic_stop = threading.Event()


def _periodic_worker(interval_hours: int = 24):
    """后台周期性检查并升级 yt-dlp。"""
    info(f"[yt-dlp 自动维护] 周期性检查线程已启动（每 {interval_hours} 小时检查一次）")
    while not _periodic_stop.is_set():
        # 等待指定间隔（每 10 秒检查一次 stop event）
        for _ in range(interval_hours * 360):
            if _periodic_stop.is_set():
                return
            time.sleep(10)

        if _periodic_stop.is_set():
            return

        try:
            info("[yt-dlp 自动维护] 执行定期自动升级检查...")
            upgrade_ytdlp(force=True)
        except Exception as e:
            warning(f"[yt-dlp 自动维护] 定期检查异常: {e}")


def start_periodic_ytdlp_updater(interval_hours: int = 24):
    """启动后台定时升级检查线程。"""
    global _periodic_thread, _periodic_stop
    if _periodic_thread is not None and _periodic_thread.is_alive():
        return
    _periodic_stop.clear()
    _periodic_thread = threading.Thread(
        target=_periodic_worker,
        args=(interval_hours,),
        daemon=True,
        name='ytdlp-periodic-updater'
    )
    _periodic_thread.start()

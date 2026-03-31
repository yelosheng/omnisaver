#!/usr/bin/env python3
"""
实时日志记录器
用于将日志同时输出到控制台和web界面
"""

from datetime import datetime
from collections import deque
import threading
import sys

# 全局日志缓冲区
log_buffer = deque(maxlen=500)
log_lock = threading.Lock()
_log_seq = 0


def _format_entry(entry):
    """将结构化日志条目格式化为前端展示文本。"""
    return f"[{entry['timestamp']}] [{entry['level']}] {entry['message']}"

def log(message, level="INFO"):
    """
    记录日志到缓冲区和控制台
    
    Args:
        message: 日志消息
        level: 日志级别 (INFO, ERROR, WARNING, SUCCESS, etc.)
    """
    global _log_seq

    # 输出到控制台
    print(f"[{level}] {message}")
    # 强制刷新输出缓冲区 - 修复SSH环境下日志不显示的问题
    sys.stdout.flush()
    
    # 添加到日志缓冲区
    with log_lock:
        _log_seq += 1
        log_buffer.append({
            'seq': _log_seq,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'level': level,
            'message': str(message),
        })

def get_logs():
    """获取日志缓冲区中的所有日志"""
    with log_lock:
        return list(log_buffer)


def get_formatted_logs():
    """获取格式化后的日志文本列表。"""
    with log_lock:
        return [_format_entry(entry) for entry in log_buffer]


def get_logs_after(seq):
    """获取指定序号之后的新日志。"""
    with log_lock:
        return [entry for entry in log_buffer if entry['seq'] > seq]


def get_latest_seq():
    """返回当前缓冲区中的最新日志序号。"""
    with log_lock:
        if not log_buffer:
            return 0
        return log_buffer[-1]['seq']


def format_log_entry(entry):
    """格式化单条日志。"""
    return _format_entry(entry)

def clear_logs():
    """清空日志缓冲区"""
    with log_lock:
        log_buffer.clear()

# 便捷函数
def info(message):
    log(message, "INFO")

def error(message):
    log(message, "ERROR")

def warning(message):
    log(message, "WARNING")

def success(message):
    log(message, "SUCCESS")

def debug(message):
    log(message, "DEBUG")

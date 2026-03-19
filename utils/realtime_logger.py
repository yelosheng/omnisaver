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

def log(message, level="INFO"):
    """
    记录日志到缓冲区和控制台
    
    Args:
        message: 日志消息
        level: 日志级别 (INFO, ERROR, WARNING, SUCCESS, etc.)
    """
    # 输出到控制台
    print(f"[{level}] {message}")
    # 强制刷新输出缓冲区 - 修复SSH环境下日志不显示的问题
    sys.stdout.flush()
    
    # 添加到日志缓冲区
    with log_lock:
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] {message}"
        log_buffer.append(log_entry)

def get_logs():
    """获取日志缓冲区中的所有日志"""
    with log_lock:
        return list(log_buffer)

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
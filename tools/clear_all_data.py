#!/usr/bin/env python3
"""
清空Twitter保存工具的所有历史数据
包括数据库记录和所有保存的文件
"""

import os
import sqlite3
import shutil
from pathlib import Path
from services.config_manager import ConfigManager

def clear_all_data():
    """清空所有数据"""
    print("🗑️  开始清理Twitter保存工具的所有数据...")
    
    # 获取当前工作目录
    current_dir = os.getcwd()
    print(f"📁 当前工作目录: {current_dir}")
    
    # 1. 清理数据库
    print("\n1️⃣  清理数据库记录...")
    db_path = "twitter_saver.db"
    
    if os.path.exists(db_path):
        try:
            # 连接数据库
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 获取当前记录数
            cursor.execute("SELECT COUNT(*) FROM tasks")
            count = cursor.fetchone()[0]
            print(f"   📊 数据库中共有 {count} 条记录")
            
            # 清空tasks表
            cursor.execute("DELETE FROM tasks")
            
            # 重置自增ID
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='tasks'")
            
            conn.commit()
            conn.close()
            
            print("   ✅ 数据库记录已清空")
        except Exception as e:
            print(f"   ❌ 清理数据库时出错: {e}")
    else:
        print("   ℹ️  数据库文件不存在")
    
    # 2. 清理saved_tweets目录
    print("\n2️⃣  清理保存的推文文件...")
    # 从配置获取保存路径
    config_manager = ConfigManager()
    saved_tweets_dir = config_manager.get_save_path()
    
    if os.path.exists(saved_tweets_dir):
        try:
            # 获取目录中的文件/文件夹数量
            items = os.listdir(saved_tweets_dir)
            print(f"   📂 saved_tweets目录中共有 {len(items)} 个项目")
            
            if items:
                # 显示前几个项目作为示例
                print(f"   📋 示例项目: {items[:3]}")
                
                # 删除整个目录
                shutil.rmtree(saved_tweets_dir)
                print("   🗂️  saved_tweets目录已删除")
                
                # 重新创建空目录
                os.makedirs(saved_tweets_dir)
                print("   📁 重新创建空的saved_tweets目录")
            else:
                print("   ℹ️  saved_tweets目录已经是空的")
                
        except Exception as e:
            print(f"   ❌ 清理saved_tweets目录时出错: {e}")
    else:
        print("   ℹ️  saved_tweets目录不存在")
        # 创建空目录
        try:
            os.makedirs(saved_tweets_dir)
            print("   📁 创建新的saved_tweets目录")
        except Exception as e:
            print(f"   ❌ 创建saved_tweets目录时出错: {e}")
    
    # 3. 清理临时文件
    print("\n3️⃣  清理临时文件...")
    temp_dirs = ["temp_media", "__pycache__"]
    
    for temp_dir in temp_dirs:
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                print(f"   🗑️  已删除临时目录: {temp_dir}")
            except Exception as e:
                print(f"   ❌ 删除{temp_dir}时出错: {e}")
        else:
            print(f"   ℹ️  临时目录不存在: {temp_dir}")
    
    # 4. 清理日志文件（如果有）
    print("\n4️⃣  清理日志文件...")
    log_files = ["app.log", "twitter_saver.log", "debug.log"]
    
    for log_file in log_files:
        if os.path.exists(log_file):
            try:
                os.remove(log_file)
                print(f"   📄 已删除日志文件: {log_file}")
            except Exception as e:
                print(f"   ❌ 删除{log_file}时出错: {e}")
    
    # 5. 验证清理结果
    print("\n5️⃣  验证清理结果...")
    
    # 检查数据库
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tasks")
            count = cursor.fetchone()[0]
            conn.close()
            
            if count == 0:
                print("   ✅ 数据库已清空")
            else:
                print(f"   ⚠️  数据库中仍有 {count} 条记录")
        except Exception as e:
            print(f"   ❌ 检查数据库时出错: {e}")
    
    # 检查saved_tweets目录
    if os.path.exists(saved_tweets_dir):
        items = os.listdir(saved_tweets_dir)
        if len(items) == 0:
            print("   ✅ saved_tweets目录已清空")
        else:
            print(f"   ⚠️  saved_tweets目录中仍有 {len(items)} 个项目")
    
    print("\n🎉 数据清理完成！")
    print("💡 建议重启应用服务以确保所有更改生效")
    print("   sudo systemctl restart uds_save_twitter.service")

if __name__ == "__main__":
    # 确认操作
    print("⚠️  WARNING: 此操作将删除所有保存的推文数据和数据库记录！")
    print("📝 这包括:")
    print("   • 所有数据库中的任务记录")
    print("   • 所有保存的推文文件（文本、图片、视频等）")
    print("   • 所有临时文件和日志")
    print()
    
    confirm = input("确定要继续吗？输入 'YES' 确认: ")
    
    if confirm == "YES":
        clear_all_data()
    else:
        print("❌ 操作已取消")
#!/usr/bin/env python3
"""
生成缺失的视频缩略图脚本
扫描已保存的推文，为没有缩略图的视频生成预览图
"""

import os
import sqlite3
import subprocess
import shutil
from pathlib import Path


class ThumbnailGenerator:
    """视频缩略图生成器"""
    
    def __init__(self):
        self.processed_count = 0
        self.generated_count = 0
        self.error_count = 0
        
    def normalize_path_cross_platform(self, path):
        """标准化路径以支持跨平台兼容性"""
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

    def find_actual_tweet_directory(self, expected_path):
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

    def generate_video_thumbnail(self, video_path: str, save_path: str) -> bool:
        """
        为视频生成缩略图
        
        Args:
            video_path: 视频文件路径
            save_path: 保存目录路径
            
        Returns:
            是否成功生成缩略图
        """
        try:
            # 检查FFmpeg是否可用
            if not shutil.which('ffmpeg'):
                print("❌ FFmpeg未找到，无法生成缩略图")
                return False
            
            # 创建thumbnails目录
            thumbnails_dir = os.path.join(save_path, 'thumbnails')
            os.makedirs(thumbnails_dir, exist_ok=True)
            
            # 生成缩略图文件名
            video_filename = os.path.basename(video_path)
            thumbnail_name = os.path.splitext(video_filename)[0] + '_thumb.jpg'
            thumbnail_path = os.path.join(thumbnails_dir, thumbnail_name)
            
            # 如果缩略图已存在，跳过
            if os.path.exists(thumbnail_path):
                print(f"   ⏭️  缩略图已存在: {thumbnail_name}")
                return True
            
            print(f"   🎬 正在生成缩略图: {thumbnail_name}")
            
            # FFmpeg命令：从视频第1秒提取帧
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-ss', '1',  # 从第1秒开始
                '-vframes', '1',  # 提取1帧
                '-q:v', '2',  # 高质量
                '-y',  # 覆盖输出文件
                thumbnail_path
            ]
            
            # 执行FFmpeg命令
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30  # 30秒超时
            )
            
            if result.returncode == 0 and os.path.exists(thumbnail_path):
                print(f"   ✅ 缩略图生成成功: {thumbnail_name}")
                return True
            else:
                print(f"   ❌ 缩略图生成失败: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"   ⏰ 缩略图生成超时: {video_filename}")
            return False
        except Exception as e:
            print(f"   ❌ 生成缩略图时出错: {e}")
            return False

    def scan_and_generate(self):
        """扫描数据库中的推文并生成缺失的视频缩略图"""
        print("🔍 开始扫描已保存的推文...")
        
        # 连接数据库
        try:
            conn = sqlite3.connect('twitter_saver.db')
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 查询所有已完成的任务
            cursor.execute('''
                SELECT id, save_path, author_username, tweet_id, media_count
                FROM tasks 
                WHERE status = 'completed' AND media_count > 0
                ORDER BY id
            ''')
            
            tasks = cursor.fetchall()
            total_tasks = len(tasks)
            
            if total_tasks == 0:
                print("📭 没有找到包含媒体的已完成任务")
                return
            
            print(f"📊 找到 {total_tasks} 个包含媒体的已完成任务")
            print("-" * 60)
            
            # 处理每个任务
            for i, task in enumerate(tasks, 1):
                task_id = task['id']
                save_path = task['save_path']
                author_username = task['author_username'] or '未知用户'
                tweet_id = task['tweet_id'] or '未知ID'
                
                print(f"[{i}/{total_tasks}] 处理任务 {task_id}: @{author_username} - {tweet_id}")
                
                if not save_path:
                    print("   ⚠️  保存路径为空，跳过")
                    continue
                
                # 标准化路径
                normalized_save_path = self.normalize_path_cross_platform(save_path)
                actual_save_path = self.find_actual_tweet_directory(normalized_save_path)
                
                if not os.path.exists(actual_save_path):
                    print(f"   ❌ 保存目录不存在: {actual_save_path}")
                    self.error_count += 1
                    continue
                
                # 检查videos目录
                videos_dir = os.path.join(actual_save_path, 'videos')
                
                if not os.path.exists(videos_dir):
                    print("   📁 没有videos目录，跳过")
                    self.processed_count += 1
                    continue
                
                # 扫描视频文件
                video_files = []
                try:
                    for filename in os.listdir(videos_dir):
                        if filename.lower().endswith(('.mp4', '.mov', '.avi', '.webm', '.mkv')):
                            video_files.append(filename)
                except Exception as e:
                    print(f"   ❌ 读取videos目录失败: {e}")
                    self.error_count += 1
                    continue
                
                if not video_files:
                    print("   📁 videos目录中没有视频文件")
                    self.processed_count += 1
                    continue
                
                print(f"   🎥 找到 {len(video_files)} 个视频文件")
                
                # 为每个视频生成缩略图
                for video_filename in sorted(video_files):
                    video_path = os.path.join(videos_dir, video_filename)
                    
                    if self.generate_video_thumbnail(video_path, actual_save_path):
                        self.generated_count += 1
                
                self.processed_count += 1
                print()  # 空行分隔
                
        except sqlite3.Error as e:
            print(f"❌ 数据库错误: {e}")
            return
        except Exception as e:
            print(f"❌ 意外错误: {e}")
            return
        finally:
            if 'conn' in locals():
                conn.close()
        
        # 输出统计信息
        print("=" * 60)
        print("📈 处理统计:")
        print(f"   处理的任务数: {self.processed_count}")
        print(f"   生成的缩略图: {self.generated_count}")
        print(f"   错误数量: {self.error_count}")
        
        if self.generated_count > 0:
            print(f"✅ 成功为 {self.generated_count} 个视频生成了缩略图！")
        else:
            print("ℹ️  没有生成新的缩略图（可能都已存在）")


def main():
    """主函数"""
    print("🎬 视频缩略图生成脚本")
    print("=" * 60)
    
    # 检查FFmpeg
    if not shutil.which('ffmpeg'):
        print("❌ 错误: 未找到FFmpeg")
        print("请安装FFmpeg并确保其在系统PATH中")
        print("\n安装说明:")
        print("Windows: 下载FFmpeg并添加到PATH，或使用: choco install ffmpeg")
        print("macOS: brew install ffmpeg")
        print("Linux: sudo apt install ffmpeg (Ubuntu/Debian) 或 sudo yum install ffmpeg (CentOS/RHEL)")
        return
    
    print("✅ FFmpeg检查通过")
    
    # 检查数据库文件
    if not os.path.exists('twitter_saver.db'):
        print("❌ 错误: 未找到twitter_saver.db数据库文件")
        print("请确保在项目根目录运行此脚本")
        return
    
    print("✅ 数据库文件检查通过")
    print()
    
    # 创建生成器并开始处理
    generator = ThumbnailGenerator()
    
    try:
        generator.scan_and_generate()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断操作")
        print(f"已处理 {generator.processed_count} 个任务，生成 {generator.generated_count} 个缩略图")
    except Exception as e:
        print(f"\n❌ 脚本执行出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
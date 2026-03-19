#!/usr/bin/env python3
"""
迁移工具: 将旧的平铺结构迁移到新的 YYYY/MM/ 层级结构

使用方法:
    python tools/migrate_to_hierarchical.py --dry-run   # 预览迁移操作
    python tools/migrate_to_hierarchical.py             # 执行迁移
    python tools/migrate_to_hierarchical.py --update-db # 同时更新数据库路径
"""

import os
import sys
import re
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime
import argparse


def parse_directory_name(dir_name: str):
    """
    解析目录名获取日期和tweet_id

    Args:
        dir_name: 目录名，格式如 "2025-10-19_1978946140788715821"

    Returns:
        (year, month, full_dir_name) 或 None
    """
    # 匹配格式: YYYY-MM-DD_tweet_id
    match = re.match(r'(\d{4})-(\d{2})-\d{2}_\d+', dir_name)
    if match:
        year = match.group(1)
        month = match.group(2)
        return (year, month, dir_name)
    return None


def migrate_directories(base_path: str, dry_run: bool = True):
    """
    迁移目录到层级结构

    Args:
        base_path: 基础路径
        dry_run: 是否只是预览（不实际移动）

    Returns:
        (成功数量, 失败数量, 迁移映射)
    """
    base_path = Path(base_path)
    success_count = 0
    fail_count = 0
    migration_map = {}  # {old_path: new_path}

    print(f"扫描目录: {base_path}")
    print(f"模式: {'预览模式 (不会实际移动文件)' if dry_run else '执行模式 (将移动文件)'}")
    print("=" * 80)

    # 获取所有需要迁移的目录
    directories_to_migrate = []

    for entry in base_path.iterdir():
        if not entry.is_dir():
            continue

        # 跳过已经是年份目录的（已迁移）
        if entry.name.isdigit() and len(entry.name) == 4:
            continue

        # 解析目录名
        parsed = parse_directory_name(entry.name)
        if parsed:
            directories_to_migrate.append((entry, parsed))

    print(f"发现 {len(directories_to_migrate)} 个需要迁移的目录\n")

    # 执行迁移
    for old_path, (year, month, dir_name) in directories_to_migrate:
        # 构建新路径
        new_path = base_path / year / month / dir_name

        # 检查新路径是否已存在
        if new_path.exists():
            print(f"❌ 跳过 (目标已存在): {dir_name}")
            print(f"   旧路径: {old_path}")
            print(f"   新路径: {new_path}")
            fail_count += 1
            continue

        # 记录映射
        migration_map[str(old_path)] = str(new_path)

        if dry_run:
            print(f"✓ 将迁移: {dir_name}")
            print(f"  从: {old_path.relative_to(base_path)}")
            print(f"  到: {new_path.relative_to(base_path)}")
            success_count += 1
        else:
            try:
                # 创建目标目录
                new_path.parent.mkdir(parents=True, exist_ok=True)

                # 移动目录
                shutil.move(str(old_path), str(new_path))

                print(f"✓ 已迁移: {dir_name}")
                print(f"  从: {old_path.relative_to(base_path)}")
                print(f"  到: {new_path.relative_to(base_path)}")
                success_count += 1

            except Exception as e:
                print(f"❌ 迁移失败: {dir_name}")
                print(f"   错误: {e}")
                fail_count += 1

    print("\n" + "=" * 80)
    print(f"迁移统计:")
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")

    return success_count, fail_count, migration_map


def update_database_paths(db_path: str, migration_map: dict, dry_run: bool = True):
    """
    更新数据库中的路径

    Args:
        db_path: 数据库路径
        migration_map: 路径映射 {old_path: new_path}
        dry_run: 是否只是预览

    Returns:
        更新的记录数
    """
    if not os.path.exists(db_path):
        print(f"数据库不存在: {db_path}")
        return 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    update_count = 0

    print("\n" + "=" * 80)
    print("更新数据库路径")
    print("=" * 80)

    # 获取所有完成的任务
    cursor.execute("SELECT id, save_path FROM tasks WHERE status='completed' AND save_path IS NOT NULL")
    tasks = cursor.fetchall()

    print(f"找到 {len(tasks)} 条已完成的任务记录\n")

    for task_id, old_path in tasks:
        if old_path in migration_map:
            new_path = migration_map[old_path]

            if dry_run:
                print(f"✓ 将更新任务 {task_id}:")
                print(f"  旧路径: {old_path}")
                print(f"  新路径: {new_path}")
            else:
                cursor.execute(
                    "UPDATE tasks SET save_path = ? WHERE id = ?",
                    (new_path, task_id)
                )
                print(f"✓ 已更新任务 {task_id}: {new_path}")

            update_count += 1

    if not dry_run:
        conn.commit()
        print(f"\n数据库更新已提交: {update_count} 条记录")
    else:
        print(f"\n预览: 将更新 {update_count} 条记录")

    conn.close()
    return update_count


def main():
    parser = argparse.ArgumentParser(
        description="迁移推文目录到层级结构 (YYYY/MM/)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 预览迁移（不实际移动）
    python tools/migrate_to_hierarchical.py --dry-run

    # 仅迁移文件
    python tools/migrate_to_hierarchical.py

    # 迁移文件并更新数据库
    python tools/migrate_to_hierarchical.py --update-db

    # 完整迁移（文件+数据库）
    python tools/migrate_to_hierarchical.py --update-db --no-dry-run
        """
    )

    parser.add_argument(
        "--base-path",
        default="/mnt/nas/saved_tweets",
        help="推文保存的基础路径 (默认: /mnt/nas/saved_tweets)"
    )

    parser.add_argument(
        "--db-path",
        default="twitter_saver.db",
        help="数据库路径 (默认: twitter_saver.db)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="预览模式，不实际移动文件 (默认)"
    )

    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="执行模式，实际移动文件"
    )

    parser.add_argument(
        "--update-db",
        action="store_true",
        help="同时更新数据库中的路径"
    )

    args = parser.parse_args()

    # 处理 dry_run 逻辑
    dry_run = args.dry_run and not args.no_dry_run

    print("=" * 80)
    print("推文目录迁移工具")
    print("=" * 80)
    print(f"基础路径: {args.base_path}")
    print(f"数据库路径: {args.db_path}")
    print(f"运行模式: {'预览 (不会实际修改)' if dry_run else '执行 (将实际修改文件和数据库)'}")
    print(f"更新数据库: {'是' if args.update_db else '否'}")
    print("=" * 80)

    if not dry_run:
        response = input("\n⚠️  确定要执行迁移吗? 这将移动文件。输入 'yes' 继续: ")
        if response.lower() != 'yes':
            print("已取消")
            return

    # 执行迁移
    success, fail, migration_map = migrate_directories(args.base_path, dry_run=dry_run)

    # 更新数据库
    if args.update_db and migration_map:
        db_updated = update_database_paths(args.db_path, migration_map, dry_run=dry_run)

        print("\n" + "=" * 80)
        print("总结:")
        print(f"  文件迁移: {success} 成功, {fail} 失败")
        print(f"  数据库更新: {db_updated} 条记录")
        print("=" * 80)

    if dry_run:
        print("\n💡 这是预览模式。要实际执行迁移，请使用: --no-dry-run")


if __name__ == "__main__":
    main()

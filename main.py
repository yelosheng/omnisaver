#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitter内容保存工具
用于保存Twitter推文和媒体文件到本地
"""

import argparse
import sys
import io
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from services.config_manager import ConfigManager
from services.twitter_service import TwitterService, TwitterScrapingError
from services.media_downloader import MediaDownloader
from services.file_manager import FileManager
from utils.url_parser import TwitterURLParser

# 修复Windows控制台编码问题
if sys.platform == 'win32':
    import os
    os.environ['PYTHONIOENCODING'] = 'utf-8'


console = Console()


def parse_arguments() -> argparse.Namespace:
    """
    解析命令行参数
    
    Returns:
        解析后的参数对象
    """
    parser = argparse.ArgumentParser(
        description="Twitter Content Saver - Save tweets and media files locally",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  python main.py https://twitter.com/user/status/1234567890
  python main.py https://x.com/user/status/1234567890 --no-media
  python main.py https://twitter.com/user/status/1234567890 --thread-only
        """
    )
    
    parser.add_argument(
        "url",
        help="Twitter tweet URL"
    )
    
    parser.add_argument(
        "--no-media",
        action="store_true",
        help="Skip downloading media files (images and videos)"
    )
    
    parser.add_argument(
        "--thread-only",
        action="store_true",
        help="Force processing as thread (even if only one tweet)"
    )
    
    parser.add_argument(
        "--single-only",
        action="store_true",
        help="Get single tweet only, don't check for threads"
    )
    
    parser.add_argument(
        "--config",
        default="config.ini",
        help="Configuration file path (default: config.ini)"
    )
    
    parser.add_argument(
        "--output",
        help="Custom output directory (overrides config file setting)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose output"
    )
    
    return parser.parse_args()


def validate_url(url: str) -> bool:
    """
    验证Twitter URL是否有效
    
    Args:
        url: 要验证的URL
        
    Returns:
        URL是否有效
    """
    return TwitterURLParser.is_valid_twitter_url(url)


def print_banner():
    """Print program banner"""
    banner = """
[bold blue]Twitter Content Saver[/bold blue]
Save tweets and media files to local storage
    """
    console.print(Panel(banner.strip(), border_style="blue"))


def print_supported_formats():
    """Print supported URL formats"""
    formats = TwitterURLParser.get_supported_formats()
    console.print("\n[yellow]Supported URL formats:[/yellow]")
    for fmt in formats:
        console.print(f"  • {fmt}")


def main():
    """Main program entry point"""
    try:
        # Parse command line arguments
        args = parse_arguments()
        
        # Print banner
        if not args.verbose:
            print_banner()
        
        # Validate URL
        if not validate_url(args.url):
            console.print(f"[red]Error: Invalid Twitter URL: {args.url}[/red]")
            print_supported_formats()
            sys.exit(1)
        
        # Load configuration
        console.print("[cyan]Loading configuration...[/cyan]")
        config_manager = ConfigManager(args.config)
        
        if not config_manager.validate_config():
            console.print("[red]Error: Configuration validation failed[/red]")
            console.print("Please check your configuration file or environment variables")
            sys.exit(1)
        
        config = config_manager.load_config()
        
        # Use custom output directory if specified
        if args.output:
            config['save_path'] = args.output
        
        if args.verbose:
            console.print(f"[dim]Configuration loaded: {args.config}[/dim]")
            console.print(f"[dim]Save path: {config['save_path']}[/dim]")
        
        # Initialize services
        console.print("[cyan]Initializing services...[/cyan]")
        
        twitter_service = TwitterService(
            max_retries=config['max_retries'],
            timeout=config['timeout_seconds'],
            use_playwright=config['use_playwright']
        )
        
        media_downloader = MediaDownloader(
            max_retries=config['max_retries'],
            timeout=config['timeout_seconds']
        )
        
        file_manager = FileManager(
            base_path=config['save_path'],
            create_date_folders=config['create_date_folders']
        )
        
        # Extract tweet ID
        tweet_id = twitter_service.extract_tweet_id(args.url)
        console.print(f"[green]Tweet ID: {tweet_id}[/green]")
        
        # Get tweet data
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Fetching tweet data...", total=None)
            
            try:
                if args.thread_only:
                    tweets = twitter_service.get_thread(tweet_id)
                elif args.single_only:
                    # Get single tweet only, don't check for threads
                    # Pass full URL to preserve username
                    single_tweet = twitter_service.get_tweet(args.url)
                    tweets = [single_tweet]
                else:
                    # Try to get single tweet first
                    # Pass full URL to preserve username
                    single_tweet = twitter_service.get_tweet(args.url)
                    # Check if it's part of a thread
                    if single_tweet.conversation_id != single_tweet.id:
                        # This is part of a thread, get complete thread
                        tweets = twitter_service.get_thread(tweet_id)
                    else:
                        tweets = [single_tweet]
                
                progress.update(task, description=f"Retrieved {len(tweets)} tweets")
                
            except TwitterScrapingError as e:
                progress.stop()
                console.print(f"[red]Error: {e}[/red]")
                sys.exit(1)
        
        # Display tweet information
        if len(tweets) == 1:
            console.print(f"[green]SUCCESS[/green] Retrieved single tweet: @{tweets[0].author_username}")
        else:
            console.print(f"[green]SUCCESS[/green] Retrieved thread: @{tweets[0].author_username} ({len(tweets)} tweets)")
        
        # Create save directory
        save_dir = file_manager.create_save_directory(tweets[0].id, tweets[0].created_at)
        console.print(f"[cyan]Save directory: {save_dir}[/cyan]")
        
        # Download media files
        all_media_files = []
        if not args.no_media:
            console.print("[cyan]Downloading media files...[/cyan]")
            
            for tweet in tweets:
                if tweet.has_media():
                    images = tweet.get_images()
                    videos = tweet.get_videos()
                    avatars = tweet.get_avatars()
                    
                    if images:
                        image_files = media_downloader.download_images(images, save_dir)
                        all_media_files.extend(image_files)
                    
                    if videos:
                        video_files = media_downloader.download_videos(videos, save_dir)
                        all_media_files.extend(video_files)
                    
                    if avatars:
                        avatar_files = media_downloader.download_avatars(avatars, save_dir)
                        all_media_files.extend(avatar_files)
            
            if all_media_files:
                console.print(f"[green]SUCCESS[/green] Downloaded {len(all_media_files)} media files")
            else:
                console.print("[yellow]No media files found[/yellow]")
        else:
            console.print("[yellow]Skipping media file download[/yellow]")
        
        # Save tweet content
        console.print("[cyan]Saving tweet content...[/cyan]")
        
        if len(tweets) == 1:
            file_manager.save_tweet_content(tweets[0], save_dir, all_media_files)
        else:
            file_manager.save_thread_content(tweets, save_dir, all_media_files)
        
        # Save metadata
        file_manager.save_metadata(tweets, save_dir, all_media_files)
        
        # Generate and display summary
        summary = file_manager.get_save_summary(save_dir, tweets, all_media_files)
        
        console.print("\n[bold green]Save completed![/bold green]")
        console.print(f"[green]SUCCESS[/green] Tweet count: {summary['tweet_count']}")
        if summary['is_thread']:
            console.print("[green]SUCCESS[/green] Type: Thread")
        else:
            console.print("[green]SUCCESS[/green] Type: Single tweet")
        
        if summary['media_count'] > 0:
            console.print(f"[green]SUCCESS[/green] Media files: {summary['media_count']}")
            if 'image_count' in summary:
                console.print(f"  - Images: {summary['image_count']}")
            if 'video_count' in summary:
                console.print(f"  - Videos: {summary['video_count']}")
        
        console.print(f"[green]SUCCESS[/green] Save location: {save_dir}")
        console.print(f"[green]SUCCESS[/green] Files created: {', '.join(summary['files_created'])}")
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Unexpected error: {e}[/red]")
        if args.verbose:
            import traceback
            console.print("[dim]" + traceback.format_exc() + "[/dim]")
        sys.exit(1)


if __name__ == "__main__":
    main()
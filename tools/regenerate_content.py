#!/usr/bin/env python3
"""
重新生成Reader模式的HTML内容，使用修复后的段落合并逻辑
"""

import json
import os
import re
from datetime import datetime
from utils.html_to_markdown import extract_readable_content

def regenerate_reader_html(save_dir):
    """重新生成指定目录的Reader模式HTML"""
    metadata_file = os.path.join(save_dir, "metadata.json")
    
    if not os.path.exists(metadata_file):
        print(f"元数据文件不存在: {metadata_file}")
        return
    
    # 读取元数据
    with open(metadata_file, 'r', encoding='utf-8') as f:
        metadata = json.load(f)
    
    if not metadata['tweets']:
        print("没有找到推文数据")
        return
    
    tweet = metadata['tweets'][0]  # 获取第一条推文
    
    # 直接使用text字段，因为它保持了正确的换行
    reader_content = tweet.get('text', '')
    if not reader_content:
        print("推文没有文本内容")
        return
    print("提取的Reader内容:")
    print("-" * 60)
    print(reader_content)
    print("-" * 60)
    
    # HTML模板 - 纯净Reader模式，只保留内容
    html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reader模式</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            max-width: 650px;
            margin: 0 auto;
            padding: 40px 20px;
            line-height: 1.8;
            background-color: #fefefe;
            color: #2c3e50;
        }}
        .reader-content {{
            font-size: 18px;
            line-height: 1.8;
            color: #2c3e50;
        }}
        .reader-content p {{
            margin-bottom: 16px;
        }}
        .reader-content strong {{
            font-weight: 600;
            color: #1a202c;
        }}
        .reader-content a {{
            color: #3182ce;
            text-decoration: none;
            border-bottom: 1px solid rgba(49, 130, 206, 0.3);
        }}
        .reader-content a:hover {{
            border-bottom-color: #3182ce;
        }}
        .mention {{
            color: #1da1f2;
            font-weight: 500;
        }}
        .hashtag {{
            color: #1da1f2;
            font-weight: 500;
        }}
        /* 打印样式 */
        @media print {{
            body {{ max-width: none; padding: 20px; }}
        }}
    </style>
</head>
<body>
    <article>
        <div class="reader-content">
            {reader_content}
        </div>
    </article>
</body>
</html>"""
    
    # 格式化Reader内容 - 正确处理Markdown到HTML的转换
    formatted_content = reader_content
    
    # 第一步：处理Markdown格式标记
    # 处理加粗文本 **text** -> <strong>text</strong>
    formatted_content = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', formatted_content)
    
    # 处理斜体文本 *text* -> <em>text</em>
    formatted_content = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', formatted_content)
    
    # 第二步：处理段落和换行
    # 分割成段落 (双换行分隔)
    paragraphs = formatted_content.split('\n\n')
    formatted_paragraphs = []
    
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if paragraph:
            # 处理段落内的单个换行为<br>
            paragraph = paragraph.replace('\n', '<br>')
            formatted_paragraphs.append(f'<p>{paragraph}</p>')
    
    formatted_content = '\n'.join(formatted_paragraphs)
    
    # 第三步：处理链接标记，转换为HTML链接
    formatted_content = re.sub(
        r'\[LINK:([^|]+)\|([^\]]+)\]',
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        formatted_content
    )
    
    # 第四步：处理@提及和#hashtag的样式
    formatted_content = re.sub(r'@(\w+)', r'<span class="mention">@\1</span>', formatted_content)
    formatted_content = re.sub(r'#(\w+)', r'<span class="hashtag">#\1</span>', formatted_content)
    
    # 生成HTML - 纯净Reader模式，只包含内容
    formatted_html = html_template.format(
        reader_content=formatted_content
    )
    
    # 保存HTML文件
    html_file = os.path.join(save_dir, "content.html")
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(formatted_html)
    
    print(f"已重新生成: {html_file}")

if __name__ == "__main__":
    save_dir = "D:/APPs/z_pan_python/twitter_collector/saved_tweets/2025-08-01_1950848530379395538"
    regenerate_reader_html(save_dir)
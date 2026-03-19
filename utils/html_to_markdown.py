#!/usr/bin/env python3
"""
HTML到Markdown转换器
将Twitter的HTML内容转换为干净的Markdown格式
"""

import re
from typing import Optional

class TwitterHTMLToMarkdown:
    """Twitter HTML内容转换为Markdown格式"""
    
    def __init__(self):
        self.patterns = [
            # 链接处理 - 先处理用户提及
            (r'<a[^>]*href="(/[^"]*)"[^>]*><span>(@\w+)</span></a>', r'[\2](https://twitter.com\1)'),
            # 链接处理 - 外部链接
            (r'<a[^>]*href="([^"]*)"[^>]*><span[^>]*>([^<]+)</span></a>', r'[\2](\1)'),
            # 简单链接
            (r'<a[^>]*href="([^"]*)"[^>]*>([^<]+)</a>', r'[\2](\1)'),
            
            # 图片处理（emoji等）
            (r'<img[^>]*alt="([^"]*)"[^>]*/?>', r'\1'),
            
            # 加粗文本
            (r'<span class="[^"]*r-b88u0q[^"]*">([^<]+)</span>', r'**\1**'),
            (r'<strong[^>]*>([^<]*)</strong>', r'**\1**'),
            (r'<b[^>]*>([^<]*)</b>', r'**\1**'),
            
            # 斜体文本
            (r'<em[^>]*>([^<]*)</em>', r'*\1*'),
            (r'<i[^>]*>([^<]*)</i>', r'*\1*'),
            
            # 代码
            (r'<code[^>]*>([^<]*)</code>', r'`\1`'),
            
            # 移除所有div和span标签，保留内容
            (r'<div[^>]*>', ''),
            (r'</div>', ''),
            (r'<span[^>]*>', ''),
            (r'</span>', ''),
            
            # 处理换行
            (r'<br[^>]*/?>', '\n'),
            (r'<p[^>]*>', '\n'),
            (r'</p>', '\n'),
            
            # 清理多余的空白
            (r'\n\s*\n\s*\n', '\n\n'),
            (r'^\s+', ''),
            (r'\s+$', ''),
        ]
    
    def convert(self, html_content: str) -> str:
        """
        将HTML内容转换为Markdown格式
        
        Args:
            html_content: 原始HTML内容
            
        Returns:
            转换后的Markdown内容
        """
        if not html_content:
            return ""
        
        markdown = html_content
        
        # 应用所有转换规则
        for pattern, replacement in self.patterns:
            markdown = re.sub(pattern, replacement, markdown, flags=re.IGNORECASE | re.DOTALL)
        
        # 后处理：清理多余的换行和空格
        lines = markdown.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            if line:  # 只保留非空行
                cleaned_lines.append(line)
            elif cleaned_lines and cleaned_lines[-1]:  # 保留段落间的空行
                cleaned_lines.append('')
        
        result = '\n'.join(cleaned_lines)
        
        # 最终清理
        result = re.sub(r'\n{3,}', '\n\n', result)  # 最多保留两个连续换行
        result = result.strip()
        
        return result
    
    def convert_twitter_content(self, html_content: str) -> str:
        """
        专门处理Twitter内容的转换
        
        Args:
            html_content: Twitter HTML内容
            
        Returns:
            格式化的Markdown内容
        """
        if not html_content:
            return ""
        
        # 预处理：修复常见的Twitter HTML结构问题
        content = html_content
        
        # 处理用户提及和hashtag
        content = re.sub(
            r'<a[^>]*href="(/\w+)"[^>]*>@(\w+)</a>',
            r'[@\2](https://twitter.com\1)',
            content
        )
        
        # 处理hashtag
        content = re.sub(
            r'<a[^>]*href="[^"]*hashtag/(\w+)"[^>]*>#(\w+)</a>',
            r'[#\2](https://twitter.com/hashtag/\1)',
            content
        )
        
        # 转换为Markdown
        return self.convert(content)
    
    def extract_readable_content(self, html_content: str, preserve_linebreaks: bool = False) -> str:
        """
        提取可读内容 - Reader模式
        类似Readability/Pocket，只保留核心内容和基本格式

        preserve_linebreaks: 为 True 时保留所有原始换行（单条推文用），
                             为 False 时启用智能合并（长文/文章用）
        """
        if not html_content:
            return ""
        
        content = html_content
        
        # 第一步：处理链接，保留链接文本但简化格式
        # 先处理用户提及 - 保留@符号，去掉链接
        content = re.sub(
            r'<a[^>]*href="[^"]*"[^>]*>@(\w+)</a>',
            r'@\1',
            content
        )
        
        # 再处理外部链接 - 保留链接文本和URL，使用特殊标记以便后续转换
        # 处理复杂的Twitter链接结构（包含嵌套span）
        def extract_link_text(match):
            url = match.group(1)
            full_tag = match.group(0)
            # 提取所有span内的文本
            span_texts = re.findall(r'<span[^>]*>([^<]*)</span>', full_tag)
            link_text = ''.join(span_texts) if span_texts else url
            # 如果链接文本是@开头，说明是用户提及，跳过
            if link_text.startswith('@'):
                return link_text
            return f'[LINK:{link_text}|{url}]'
        
        content = re.sub(
            r'<a[^>]*href="([^"]*)"[^>]*>.*?</a>',
            extract_link_text,
            content,
            flags=re.DOTALL
        )
        
        # Hashtag - 保留#符号，去掉链接
        content = re.sub(
            r'<a[^>]*href="[^"]*hashtag/[^"]*"[^>]*>#(\w+)</a>',
            r'#\1',
            content
        )
        
        # 第二步：处理格式标签，保留重要格式
        # 加粗文本 (Twitter特有的加粗class)
        content = re.sub(r'<span[^>]*class="[^"]*r-b88u0q[^"]*"[^>]*>([^<]+)</span>', r'**\1**', content)
        content = re.sub(r'<strong[^>]*>([^<]*)</strong>', r'**\1**', content)
        content = re.sub(r'<b[^>]*>([^<]*)</b>', r'**\1**', content)
        
        # 斜体文本
        content = re.sub(r'<em[^>]*>([^<]*)</em>', r'*\1*', content)
        content = re.sub(r'<i[^>]*>([^<]*)</i>', r'*\1*', content)
        
        # 第三步：处理emoji图片，转换为alt文本
        content = re.sub(r'<img[^>]*alt="([^"]*)"[^>]*/?>', r'\1', content)
        
        # 第四步：移除所有HTML标签和Twitter特有的CSS类
        # 先把换行类标签转为 \n，再统一清除其余标签（否则 <br> 会被替换成空格丢失换行）
        content = re.sub(r'<br\s*/?>', '\n', content, flags=re.IGNORECASE)
        content = re.sub(r'</?p[^>]*>', '\n', content, flags=re.IGNORECASE)
        content = re.sub(r'<[^>]+>', ' ', content)
        
        # 第五步：清理空白字符 - 保留段落结构
        # 先保护重要的换行（在标题前后）
        content = re.sub(r'(\*\*[^*]+\*\*)', r'\n\1\n', content)  # 标题前后加换行
        
        # 处理多余空格，但保留换行
        lines = content.split('\n')
        cleaned_lines = []
        for line in lines:
            line = re.sub(r'\s+', ' ', line.strip())  # 行内多个空格合并
            cleaned_lines.append(line)
        
        content = '\n'.join(cleaned_lines)
        content = re.sub(r'\n{3,}', '\n\n', content)  # 最多保留两个换行
        content = content.strip()
        
        # 第六步：格式美化 - 智能段落合并和格式化
        # preserve_linebreaks=True 时（单条推文）跳过合并，直接保留每行
        lines = content.split('\n')
        formatted_lines = []

        if preserve_linebreaks:
            # 单条推文：原样保留每行，不做智能合并
            for line in lines:
                formatted_lines.append(line.strip())
        else:
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if not line:
                    i += 1
                    continue

                # 检测是否为标题行（加粗内容且相对独立）
                if '**' in line and line.count('**') >= 2:
                    # 如果前面有内容，添加段落分隔
                    if formatted_lines and formatted_lines[-1]:
                        formatted_lines.append('')  # 空行作为段落分隔
                    formatted_lines.append(line)
                    formatted_lines.append('')  # 标题后也添加空行
                    i += 1
                # 检测列表项
                elif line.startswith(('1. ', '2. ', '3. ', '4. ', '5. ')) or line.startswith('·'):
                    formatted_lines.append(line)
                    i += 1
                # 普通内容 - 智能合并短句和连接词
                else:
                    # 如果当前行是短连接词，向前合并到前一个段落
                    if len(line) <= 3 and line in ['和', '但', '或', '且', '以及', '但是', '并且', '而且'] and formatted_lines:
                        # 将连接词合并到前一个段落
                        formatted_lines[-1] = formatted_lines[-1] + ' ' + line

                        # 查看下一行，如果是相关内容也一起合并
                        j = i + 1
                        while j < len(lines):
                            next_line = lines[j].strip()
                            if not next_line:
                                j += 1
                                continue

                            # 如果下一行是标题，也合并进来（因为连接词通常连接相关内容）
                            if ('**' in next_line and next_line.count('**') >= 2):
                                formatted_lines[-1] = formatted_lines[-1] + ' ' + next_line
                                j += 1
                                break
                            # 如果是普通内容且比较短，也合并
                            elif len(next_line) < 50:
                                formatted_lines[-1] = formatted_lines[-1] + ' ' + next_line
                                j += 1
                                break
                            else:
                                break

                        i = j
                    else:
                        # 收集连续的短内容行，合并成一个段落
                        paragraph_parts = [line]
                        j = i + 1

                        # 向前看，合并短句
                        while j < len(lines):
                            next_line = lines[j].strip()
                            if not next_line:
                                j += 1
                                continue

                            # 如果下一行是标题或列表，停止合并
                            if ('**' in next_line and next_line.count('**') >= 2) or \
                               next_line.startswith(('1. ', '2. ', '3. ', '4. ', '5. ', '·')):
                                break

                            # 只合并非常短的句子片段
                            if len(next_line) < 10 and not next_line.endswith(('。', '！', '？', '：')):
                                paragraph_parts.append(next_line)
                                j += 1
                            else:
                                break

                        # 将收集的部分合并成一个段落
                        merged_paragraph = ' '.join(paragraph_parts)
                        formatted_lines.append(merged_paragraph)
                        i = j
        
        result = '\n'.join(formatted_lines)
        result = re.sub(r'\n{3,}', '\n\n', result)  # 最多保留两个换行
        
        return result.strip()


def convert_html_to_markdown(html_content: str) -> str:
    """
    将HTML内容转换为Markdown（便捷函数）
    
    Args:
        html_content: HTML内容
        
    Returns:
        Markdown格式内容
    """
    converter = TwitterHTMLToMarkdown()
    return converter.convert_twitter_content(html_content)


def extract_readable_content(html_content: str, preserve_linebreaks: bool = False) -> str:
    """
    提取可读内容 - Reader模式（便捷函数）
    类似Readability/Pocket，专注内容，去掉UI噪音

    Args:
        html_content: 原始HTML内容
        preserve_linebreaks: 为 True 时保留原始换行（单条推文用）

    Returns:
        Reader模式的纯净内容
    """
    converter = TwitterHTMLToMarkdown()
    return converter.extract_readable_content(html_content, preserve_linebreaks=preserve_linebreaks)


if __name__ == "__main__":
    # 测试转换器
    test_html = '''<span class="css-1jxf684 r-bcqeeo r-1ttztb7 r-qvutc0 r-poiln3"><span class="r-b88u0q">Claude 最近发布了两个新功能：[移动端生成日历事件]</span><span> 和 </span><span class="r-b88u0q">[Artifacts 升级] </span><span>但没有详细说明， </span></span><div class="css-175oi2r r-xoduu5"><span class="r-18u37iz"><a dir="ltr" href="/simonw" role="link" class="css-1jxf684 r-bcqeeo r-1ttztb7 r-qvutc0 r-poiln3 r-1loqt21" style="color: rgb(29, 155, 240);"><span>@simonw</span></a></span></div>'''
    
    result = convert_html_to_markdown(test_html)
    print("原始HTML:")
    print(test_html)
    print("\n转换后的Markdown:")
    print(result)
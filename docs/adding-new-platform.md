# 新增平台保存功能开发指南

本文档描述为 OmniSaver 新增一个保存平台（如抖音、Bilibili、Instagram 等）所需的全部改动，以及每一步的技术规范。

---

## 架构概述

OmniSaver 使用三层架构，新增平台只需按照固定模式分别在每层加一个"插槽"，不影响任何现有平台：

```
services/<platform>_service.py   ← 新建：平台专属下载逻辑
        ↓
services/background.py           ← 修改：注册任务处理器和工厂函数
        ↓
app.py                           ← 修改：URL 检测、路由提交、视图渲染
```

---

## 步骤一：创建 `services/<platform>_service.py`

这是唯一需要大量编写的文件，其他步骤都是照猫画虎。

### 接口规范

参考文件：`services/youtube_service.py`、`services/xhs_service.py`

```python
class <Platform>ServiceError(Exception):
    pass


class <Platform>Service:

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            from pathlib import Path
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            base_path = str(Path(data_dir) / 'saved_<platform>')
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    @classmethod
    def is_valid_<platform>_url(cls, url: str) -> bool:
        """返回 True 表示该 URL 属于本平台，用于自动 URL 类型识别。"""
        ...

    def save_<content>(self, url: str) -> dict:
        """
        下载并保存内容到本地，返回结果字典。

        必须包含的返回字段：
            save_path        str   — 已创建的保存目录的绝对路径
            <id_field>       str   — 内容唯一 ID（如 video_id、post_id），写入 tasks.tweet_id
            author_username  str   — 作者用户名（无 @ 符号）
            author_name      str   — 作者显示名
            tweet_text       str   — 纯文本摘要（最多 500 字，写入 DB 用于预览）
            media_count      int   — 已下载的媒体文件数量

        可选字段：
            title            str   — 标题（若不提供则从 metadata.json 读取）

        保存目录内必须生成的文件（至少满足其中一种）：
            metadata.json    — 含 title 字段，用于视图页标题和 saved 列表标题
            content.md       — Markdown 正文（包含图片/视频相对路径）
            content.txt      — 纯文本正文（备选）
            content.html     — Reader 模式 HTML（可选）
            avatar.jpg       — 作者头像（可选）
            images/          — 图片目录
            videos/          — 视频目录
            thumbnails/      — 视频缩略图（可选，FFmpeg 生成）
        """
        ...
```

### 保存目录结构

建议按照以下惯例命名保存目录，以保持与现有平台的一致性：

```
<base_path>/saved_<platform>/YYYY-MM-DD_<title>_<id>/
```

示例（参考 `youtube_service.py`）：

```python
from datetime import datetime
import re

def _make_save_dir(self, video_id: str, title: str, created_at: datetime = None) -> Path:
    date_str = (created_at or datetime.now()).strftime('%Y-%m-%d')
    safe_title = re.sub(r'[^\w\u4e00-\u9fff\- ]', '', title)[:40].strip()
    folder_name = f'{date_str}_{safe_title}_{video_id}'
    if self.create_date_folders:
        save_dir = self.base_path / date_str[:7]  # YYYY-MM
    else:
        save_dir = self.base_path
    save_dir = save_dir / folder_name
    save_dir.mkdir(parents=True, exist_ok=True)
    return save_dir
```

### metadata.json 格式（必须包含 `title`）

```json
{
    "title": "视频标题",
    "author": "作者名",
    "author_username": "用户名",
    "url": "原始 URL",
    "platform": "<platform>",
    "saved_at": "2026-01-01T12:00:00"
}
```

---

## 步骤二：在 `services/background.py` 注册

### 2.1 新增工厂函数

在文件末尾（或紧跟 `make_webpage_service()` 之后）添加：

```python
def make_<platform>_service():
    """Instantiate <Platform>Service with configured save path."""
    from services.<platform>_service import <Platform>Service
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    return <Platform>Service(base_path, create_date_folders=create_date_folders)
```

> **注意**：不要在模块顶层 import 新 service，使用延迟 import（在函数内 `from services...`），可避免循环依赖和可选依赖问题。

### 2.2 新增任务处理器

参考 `process_youtube_task()` 或 `process_xhs_task()`，整体结构固定：

```python
def process_<platform>_task(task_id: int, url: str):
    """Queue worker handler for <Platform> tasks."""
    conn = get_db_connection()
    try:
        # 1. 标记 processing
        conn.execute(
            'UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
            ('processing', format_time_for_db(get_current_time()), task_id)
        )
        conn.commit()
        conn.close()

        # 2. 调用 service
        svc = make_<platform>_service()
        result = svc.save_<content>(url)
        slug = generate_unique_slug()
        now = format_time_for_db(get_current_time())

        # 3. 写回 DB（content_type 硬编码为平台名）
        conn = get_db_connection()
        conn.execute(
            '''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?,
               author_username=?, author_name=?, save_path=?, tweet_text=?,
               share_slug=?, media_count=?, content_type='<platform>' WHERE id=?''',
            (now, result['<id_field>'],
             result.get('author_username', ''), result.get('author_name', ''),
             result['save_path'], result.get('tweet_text', '')[:500],
             slug, result.get('media_count', 0),
             task_id)
        )

        # 4. 更新 FTS 全文索引
        full_text = _read_full_text(result['save_path']) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''),
                   full_text, title=_read_title(result['save_path']))
        conn.commit()
        conn.close()
        success(f'[<Platform> Task {task_id}] Saved: {result.get("title", url)}')

    except Exception as e:
        error(f'[<Platform> Task {task_id}] Failed: {e}')
        try:
            conn2 = get_db_connection()
            conn2.execute(
                "UPDATE tasks SET status='failed', error_message=? WHERE id=?",
                (str(e)[:500], task_id)
            )
            conn2.commit()
            conn2.close()
        except Exception:
            pass
```

### 2.3 在 `queue_processor()` 添加分发分支

找到 `queue_processor()` 函数中的 dispatch 块（约 794 行），加一行：

```python
if _content_type == 'xhs':
    process_xhs_task(task_id, url)
elif _content_type == '<platform>':          # ← 新增
    process_<platform>_task(task_id, url)    # ← 新增
elif _content_type == 'wechat':
    process_wechat_task(task_id, url)
elif _content_type == 'youtube':
    process_youtube_task(task_id, url)
elif _content_type == 'webpage':
    process_webpage_task(task_id, url)
else:
    process_tweet_task(task_id, url)
```

---

## 步骤三：修改 `app.py`

### 3.1 顶部 import

在 `app.py` 顶部现有 service import 区域添加：

```python
from services.<platform>_service import <Platform>Service, <Platform>ServiceError
```

### 3.2 URL 自动识别（`submit_url()` 函数，约 326 行）

在 content_type 检测链中加一个 `elif`，放在 `webpage` 之前：

```python
if YoutubeService.is_valid_youtube_url(url):
    content_type = 'youtube'
elif <Platform>Service.is_valid_<platform>_url(url):   # ← 新增
    content_type = '<platform>'                         # ← 新增
elif XHSService.is_valid_xhs_url(url):
    content_type = 'xhs'
elif WechatService.is_valid_wechat_url(url):
    content_type = 'wechat'
elif TwitterURLParser.is_valid_twitter_url(url):
    content_type = 'tweet'
...
```

### 3.3 视图页内容渲染（`show_tweet()` 函数，约 891 行）

根据新平台的内容格式，选择以下之一：

**情形 A：内容以 `content.md` 存储（图文类，同 XHS/微信）**

将 `'<platform>'` 加入现有 XHS/WeChat 渲染块的条件中：

```python
if content_type in ('xhs', 'wechat', '<platform>') and not tweet_html:
```

如有平台特有的噪声字段需过滤，在块内加：

```python
if content_type == '<platform>':
    md_text = _re.sub(r'\*\*某字段\*\*:.*\n?', '', md_text)
```

**情形 B：视频类（同 YouTube，有 `content.md` + 字幕）**

参考 `if content_type == 'youtube' and not tweet_html:` 块，复制并根据新平台格式调整。

**情形 C：纯 HTML（内容写入 `content.html`）**

`show_tweet()` 已通用读取 `content.html`，无需新增代码。

### 3.4 视图页标题回退标签（`show_tweet()` 函数，约 1003 行）

在 `_type_labels` 字典加一项：

```python
_type_labels = {
    'tweet': 'Tweet', 'article': 'Article', 'xhs': 'XHS Post',
    'wechat': 'WeChat Article', 'youtube': 'YouTube Video', 'webpage': 'Webpage',
    '<platform>': '<显示名>',    # ← 新增
}
```

### 3.5 媒体网格抑制（`show_tweet()` 函数，约 980 行）

如果新平台的媒体已内嵌在 HTML/Markdown 中（无需在页面底部单独展示媒体网格），将平台名加入抑制条件：

```python
display_media_files = [] if (
    content_type in ('wechat', 'youtube', 'webpage', '<platform>') and tweet_html
) or _has_thread_html else media_files
```

### 3.6 （可选）独立 API 提交端点

若需要供 Tampermonkey 脚本或外部工具直接调用，参考 `api_submit_youtube()` 添加：

```python
@app.route('/api/submit/<platform>', methods=['POST'])
@login_required
def api_submit_<platform>():
    """Submit a <Platform> URL for download."""
    try:
        url = None
        if request.is_json:
            data = request.get_json()
            url = data.get('url') if data else None
        if not url and request.form:
            url = request.form.get('url')
        if not url and request.data:
            url = request.data.decode('utf-8').strip()
        if not url:
            url = request.args.get('url')

        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        if not <Platform>Service.is_valid_<platform>_url(url):
            return jsonify({'success': False, 'error': 'Invalid <Platform> URL'}), 400

        conn = get_db_connection()
        existing = conn.execute('SELECT id, status FROM tasks WHERE url = ?', (url,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': True, 'duplicate': True,
                            'task_id': existing['id'], 'status': existing['status']}), 200

        now = format_time_for_db(get_current_time())
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tasks (url, status, created_at, content_type) VALUES (?, 'pending', ?, '<platform>')",
            (url, now)
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        enqueue_task(task_id, url)
        return jsonify({'success': True, 'task_id': task_id, 'status': 'pending',
                        'queue_size': processing_queue.qsize()}), 201

    except <Platform>ServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': 'Internal server error', 'message': str(e)}), 500
```

---

## 步骤四：验证

```bash
# 1. import 检查
python -c "from services.<platform>_service import <Platform>Service; print('service OK')"
python -c "from app import app; print('app import OK')"

# 2. 启动服务
python run_web.py

# 3. 提交一个真实 URL 确认 completed
# 4. 访问 /view/<slug> 确认内容正常显示
# 5. 访问 /saved 确认标题和预览图正常
# 6. 重启服务，确认 pending 任务自动恢复
```

---

## 不需要改动的部分

| 模块 | 原因 |
|------|------|
| `services/db.py` | 完全通用，无平台特定逻辑 |
| 数据库 schema | `content_type` TEXT 字段已存在，无需迁移 |
| 任务队列 / 重试机制 | 完全通用 |
| FTS 全文搜索 | `fts_upsert()` 通用，新平台自动索引 |
| `/saved` 列表页 | 通用查询，新 `content_type` 自动出现 |
| `/tasks` 任务监控 | 通用，零改动 |
| Telegram Bot | 通过统一 `submit_url()` 提交，零改动 |
| `run_web.py` 启动器 | 零改动 |

---

## 各平台实现参考

| 平台 | Service 文件 | 使用工具 | 返回 ID 字段 |
|------|-------------|----------|-------------|
| YouTube | `youtube_service.py` | `yt-dlp` (subprocess) | `video_id` |
| XiaoHongShu | `xhs_service.py` | `mcporter` npm (MCP) | `feed_id` |
| WeChat | `wechat_service.py` | `wechat-article-for-ai` (subprocess) | `article_id` |
| Webpage | `webpage_service.py` | Playwright + Readability.js | `page_id` |

新平台（如抖音/TikTok）建议使用 `yt-dlp`，它同时支持抖音、Bilibili、Instagram 等数百个平台：

```bash
# 测试 yt-dlp 是否支持目标平台
yt-dlp --simulate <url>
```

---

## 最小工作量估算

| 任务 | 代码量 |
|------|--------|
| `services/<platform>_service.py` | ~100–200 行（主要是下载逻辑） |
| `services/background.py` 改动 | ~30 行（工厂函数 + 任务处理器 + dispatch 行） |
| `app.py` 改动 | ~5–20 行（import + URL 检测 + 视图渲染调整） |
| **合计框架侧改动** | **~35–55 行** |

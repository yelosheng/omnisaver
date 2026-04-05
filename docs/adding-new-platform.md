# 新增平台保存功能开发指南

本文档描述为 OmniSaver 新增一个保存平台（如抖音、微博、Bilibili、Instagram 等）所需的全部改动，以及每一步的技术规范。

如果你要接入像 Pinterest 这类带分享短链的平台，额外要注意两点：
1. `extract_url_from_share_text()` 必须能直接识别分享文案里的短链，例如 `https://pin.it/4qbO3p6JQ`。
2. `save_<content>()` 内部要负责把短链解析成最终的 canonical URL，再提取真实内容 ID。

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

参考文件：`services/douyin_service.py`、`services/weibo_service.py`、`services/instagram_service.py`

```python
class <Platform>ServiceError(Exception):
    pass


class <Platform>Service:

    _URL_RE = re.compile(r'https?://...') # 定义该平台的 URL 正则

    def __init__(self, base_path: str = None, create_date_folders: bool = True):
        if base_path is None:
            from pathlib import Path
            data_dir = os.environ.get('DATA_DIR', str(Path(__file__).parent.parent))
            # 必须使用全局统一的图库目录，不要自行创建 saved_<platform> 子目录
            base_path = str(Path(data_dir) / 'saved_tweets')
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.create_date_folders = create_date_folders

    @classmethod
    def is_valid_<platform>_url(cls, url: str) -> bool:
        """返回 True 表示该 URL 属于本平台，用于自动 URL 类型识别。"""
        return bool(cls._URL_RE.search(url))

    @classmethod
    def extract_url_from_share_text(cls, text: str) -> str:
        """
        核心功能：从复杂的分享文本（含中文字符、表情等）中提取出纯净的 URL。
        示例：'3.05 复制打开微博... https://weibo.com/xxx/yyy ...' -> 'https://weibo.com/xxx/yyy'
        """
        m = cls._URL_RE.search(text)
        return m.group(0).rstrip('/') if m else ''

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
            content.md       — Markdown 正文（需处理 # 标签转义：re.sub(r'(?m)^#', r'\#', text)）
            content.txt      — 纯文本正文（备选）
            avatar.jpg       — 作者头像。**强烈建议抓取**：只要保存目录下存在此文件，前端列表和详情页会自动识别并显示作者头像。
            images/          — 图片目录
            videos/          — 视频目录
            thumbnails/      — 视频缩略图（可选）
        """
        ...

        ### 作者头像处理规范

        为了保持 UI 的一致性，建议在 `save_xxx` 方法中包含以下逻辑：
        1. 从平台元数据中提取作者头像的原始 URL。
        2. 使用 `urllib` 或 `requests` 下载该图片。
        3. 将其保存为 `post_dir / 'avatar.jpg'`。
        4. 系统后端 (`app.py`) 会自动检测该文件的存在，并将其转化为前端可用的 `avatar_url`。

        ### 保存目录机制与生成规范

        **核心规则 1：统一存储于基础层级且按「执行保存时间」自动归档**
        所有平台必须将媒体和元数据统一保存在由系统配置（`self.base_path`，默认 `saved_tweets`）所指定的同一个根目录下，并且默认开启按「运行保存任务当时的执行日期」（`YYYY/MM`）归档。
        **绝对禁止**任何平台代码使用抓取帖子的“发布时间”(pub_date)来生成归档的年份与月份目录，这会导致老帖散落隐匿。必须使用当前的 `datetime.now()` 作为存储目录与包名称的生成依据！

        **核心规则 2：严禁平台专属根目录**
        绝对禁止在指定的 `base_path` 下强行植入或硬编码各平台的专属子目录（如 `saved_douyin` 或 `saved_zhihu`）。这样做是为了保证所有收藏资产能够在统一视图中被极度打散扁平、高效跨平台联合搜索或备份。

        **标准存放路径代码范例：**
        ```python
        # 获取最新的当前保存时间，这极其重要！请勿使用原始帖子的发布时间来建立归档路径！
        save_time = datetime.now()
        safe_title = re.sub(r'[^\w\u4e00-\u9fa5]+', '_', title)[:40]
        
        # 终端保存文件夹名称使用 "YYYY-MM-DD_title_id" 的标准组合
        folder_name = f"{save_time.strftime('%Y-%m-%d')}_{safe_title}_{item_id}"
        
        if self.create_date_folders:
            # 必须生成 "YYYY/MM" (2026/04) 的父级归档目录
            # 注意：请务必确保每次都用字符串形式调用再拼接对象，例如：
            post_dir = self.base_path / save_time.strftime('%Y') / save_time.strftime('%m') / folder_name
        else:
            post_dir = self.base_path / folder_name
        
        post_dir.mkdir(parents=True, exist_ok=True)
        ```
---

## 步骤二：在 `services/background.py` 注册

### 2.1 新增工厂函数

在文件约 280 行附近（`make_webpage_service()` 之后）添加：

```python
def make_<platform>_service():
    """Instantiate <Platform>Service with configured save path."""
    from services.<platform>_service import <Platform>Service
    base_path = _config_manager.get_save_path() if _config_manager else os.path.join(DATA_DIR, 'saved_tweets')
    create_date_folders = _config_manager.get_create_date_folders() if _config_manager else True
    return <Platform>Service(base_path, create_date_folders=create_date_folders)
```

### 2.2 新增任务处理器

参考 `process_weibo_task()`，整体结构固定：

```python
def process_<platform>_task(task_id: int, url: str):
    """Queue worker handler for <Platform> tasks."""
    conn = get_db_connection()
    try:
        # 1. 标记正在处理
        conn.execute('UPDATE tasks SET status = ?, processed_at = ? WHERE id = ?',
                     ('processing', format_time_for_db(get_current_time()), task_id))
        conn.commit(); conn.close()

        # 2. 执行下载
        svc = make_<platform>_service()
        result = svc.save_<content>(url)
        
        # 3. 更新数据库
        slug = generate_unique_slug()
        conn = get_db_connection()
        conn.execute('''UPDATE tasks SET status='completed', processed_at=?, tweet_id=?,
                        author_username=?, author_name=?, save_path=?, tweet_text=?,
                        share_slug=?, media_count=?, content_type='<platform>' WHERE id=?''',
                     (format_time_for_db(get_current_time()), result['<id_field>'],
                      result.get('author_username', ''), result.get('author_name', ''),
                      result['save_path'], result.get('tweet_text', '')[:500],
                      slug, result.get('media_count', 0), task_id))

        # 4. 更新全文索引
        full_text = _read_full_text(result['save_path']) or result.get('tweet_text', '')
        fts_upsert(conn, task_id, result.get('author_name', ''), result.get('author_username', ''),
                   full_text, title=result.get('title'))
        conn.commit(); conn.close()
    except Exception as e:
        # 错误处理...
```

### 2.3 在 `queue_processor()` 添加分发

找到 `queue_processor()` 中的 dispatch 块，按字母顺序或逻辑顺序加入：

```python
elif _content_type == '<platform>':
    process_<platform>_task(task_id, url)
```

---

## 步骤三：修改 `app.py` (后端逻辑)

### 3.1 增加 URL 自动提取逻辑

在 `submit_url()` 和 `api_submit()` 中，**必须优先执行 URL 提取**，然后再检测平台类型。这样可以支持直接粘贴移动端 App 生成的带文案分享链接。

```python
# app.py 约 320 行
def submit_url():
    ...
    # 优先提取纯净 URL
    <platform>_url = <Platform>Service.extract_url_from_share_text(url)
    if <platform>_url:
        url = <platform>_url
        content_type = '<platform>'
    elif YoutubeService.is_valid_youtube_url(url):
        ...
```

### 3.2 视图页渲染配置

1.  **Markdown 渲染**：将新平台加入 `show_tweet()` 中 `if content_type in ('xhs', 'wechat', 'douyin', 'weibo', '<platform>')` 的判断。
2.  **媒体网格抑制**：如果视频/图片已在 Markdown 中内联显示，请在 `display_media_files` 的赋值逻辑中加入该平台名，防止页面下方出现重复的媒体预览。
3.  **标题标签**：在 `_type_labels` 字典中增加对应的显示名称。

---

## 步骤四：修改前端模板 (UI 图标)

这是让新平台看起来像原生支持的关键。

### 4.1 增加平台筛选器

在 `templates/saved.html` 和 `templates/search.html` 的平台下拉菜单中增加一个 checkbox：

```html
<li><label class="dropdown-item"><input type="checkbox" class="platform-cb me-2" value="<platform>"> <显示名></label></li>
```

### 4.2 增加平台图标 (SVG)

在上述文件的 `addTweetsToGrid` 或 `renderResults` JavaScript 函数中，为 `sourceBadge` 增加判断：

```javascript
// 使用来自 https://github.com/GLINCKER/thesvg 的标准图标
} else if (item.content_type === '<platform>') {
    sourceBadge = `<svg title="<Name>" ...>...</svg>`;
}
```

### 4.3 详情页底部图标

在 `templates/tweet_display.html` 的底部 `tweet-footer` 区域增加图标判断：

```html
{% elif tweet.content_type == '<platform>' %}
<svg ...>...</svg>
```

---

## 步骤五：验证

1.  **Import 检查**：启动服务前运行 `python -c "from services.<platform>_service import <Platform>Service; print('OK')"`。
2.  **端到端测试**：
    *   在首页提交一个带文案的分享链接。
    *   在任务队列中观察其是否正确识别为 `<platform>` 类型。
    *   保存成功后，检查预览卡片图标是否正确。
    *   进入详情页，确认图片/视频不重复显示且排版正常。

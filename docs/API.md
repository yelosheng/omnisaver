# OmniSaver API 文档

**Base URL**: `http://<your-server>:6201`

---

## 认证

大多数 API 端点**不需要登录**（设计为允许 Tampermonkey 等外部工具直接调用）。少数管理类接口需要 session cookie，通过 `POST /login` 获取。

---

## 核心 API

### 1. 提交 URL 保存任务

**`POST /api/submit`**

自动识别 Twitter/X、XiaoHongShu、微信文章、YouTube、网页等链接。

**请求格式（任选其一）：**

```http
# JSON
POST /api/submit
Content-Type: application/json
{"url": "https://x.com/user/status/123456"}

# Form
POST /api/submit
Content-Type: application/x-www-form-urlencoded
url=https://x.com/user/status/123456

# Query string
POST /api/submit?url=https://x.com/user/status/123456

# 纯文本 body（仅 Twitter URL）
POST /api/submit
Content-Type: text/plain
https://x.com/user/status/123456
```

**响应 - 新任务（201）：**
```json
{
  "success": true,
  "message": "Task added to queue",
  "task_id": 42,
  "url": "https://x.com/...",
  "status": "pending",
  "queue_size": 1
}
```

**响应 - 重复 URL（200）：**
```json
{
  "success": true,
  "message": "Task already exists (status: completed)",
  "task_id": 42,
  "url": "https://x.com/...",
  "status": "completed",
  "duplicate": true
}
```

**支持的平台（自动检测）：**
- Twitter/X: `x.com`, `twitter.com`
- 小红书: `xiaohongshu.com`, `xhslink.com`，分享文字中的链接
- 微信公众号: `mp.weixin.qq.com`
- YouTube: `youtube.com`, `youtu.be`
- 通用网页: 其他 http/https URL

---

### 2. 查询任务状态

**`GET /api/status/<task_id>`**

```http
GET /api/status/42
```

**响应：**
```json
{
  "success": true,
  "task": {
    "id": 42,
    "url": "https://x.com/...",
    "status": "completed",
    "content_type": "tweet",
    "created_at": "2026-03-23 10:00:00",
    "processed_at": "2026-03-23 10:01:00",
    "author_username": "user",
    "author_name": "User Name",
    "tweet_text": "推文内容...",
    "tweet_count": 1,
    "media_count": 2,
    "is_thread": false,
    "share_slug": "abc123",
    "error_message": null,
    "retry_count": 0,
    "next_retry_time": null
  }
}
```

**status 枚举值：**
- `pending` — 等待处理
- `processing` — 处理中
- `completed` — 已完成
- `failed` — 失败

**content_type 枚举值：**
- `tweet` — Twitter/X 推文
- `article` — Twitter 文章（长文）
- `xhs` — 小红书
- `wechat` — 微信公众号
- `youtube` — YouTube 视频
- `webpage` — 通用网页

---

### 3. 获取任务队列列表

**`GET /api/tasks`**

```http
GET /api/tasks?page=1&per_page=20&status=pending
```

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `page` | int | 页码，默认 1 |
| `per_page` | int | 每页数量，默认 20 |
| `status` | string | 筛选状态（可选） |

**响应：**
```json
{
  "tasks": [...],
  "total": 100,
  "page": 1,
  "per_page": 20,
  "pages": 5
}
```

---

### 4. 获取已保存内容列表

**`GET /api/saved`**

```http
GET /api/saved?page=1&per_page=20&search=关键词&content_type=tweet&date_from=2026-01-01&date_to=2026-03-23
```

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `page` | int | 页码，默认 1 |
| `per_page` | int | 每页数量，默认 20 |
| `search` | string | 全文搜索（支持 Google 语法：`金价 避险 -美联储` / `OR` / `"精确短语"`） |
| `content_type` | string | 平台筛选，多个用逗号分隔：`tweet,xhs,wechat,youtube,webpage` |
| `date_from` | string | 开始日期 `YYYY-MM-DD` |
| `date_to` | string | 结束日期 `YYYY-MM-DD` |

**响应（每条记录）：**
```json
{
  "saved": [
    {
      "id": 42,
      "url": "...",
      "status": "completed",
      "content_type": "tweet",
      "author_username": "user",
      "author_name": "User Name",
      "preview_text": "推文前140字...",
      "has_avatar": true,
      "avatar_url": "/media/42/avatar.jpg",
      "has_media_preview": true,
      "share_slug": "abc123",
      "processed_at": "2026-03-23 10:01:00",
      "tweet_count": 1,
      "media_count": 2
    }
  ],
  "total": 500,
  "page": 1,
  "per_page": 20,
  "pages": 25
}
```

---

### 5. 媒体文件访问

**`GET /media/<task_id>/preview`**

返回该任务的第一个预览图（优先缩略图 > 图片 > 视频）。

**`GET /media/<task_id>/<path>`**

获取具体文件，例如：
- `/media/42/avatar.jpg` — 作者头像
- `/media/42/images/photo_1.jpg` — 图片
- `/media/42/videos/video_1.mp4` — 视频
- `/media/42/thumbnails/thumb_1.jpg` — 视频缩略图

---

### 6. 公开分享链接

**`GET /view/<share_slug>`**

无需登录，返回 HTML 页面，可直接分享给他人。

---

### 7. 系统状态

**`GET /api/status`**

```json
{
  "queue_size": 0,
  "is_processing": false,
  "current_task_id": null,
  "total_tasks": 500,
  "pending_tasks": 0,
  "processing_tasks": 0,
  "completed_tasks": 490,
  "failed_tasks": 10
}
```

---

### 8. 实时日志（SSE）

**`GET /api/logs/stream`**

Server-Sent Events 流，适合在 App 中实时展示处理进度。

**`GET /api/logs/recent`**

获取最近日志快照，返回 JSON。

---

## 典型安卓 App 使用流程

```
1. 用户通过系统分享菜单将链接分享到 App
2. POST /api/submit  → 获取 task_id
3. 轮询 GET /api/status/<task_id>，直到 status = "completed" 或 "failed"
4. 展示内容：preview_text + avatar_url + /media/<id>/preview
5. GET /api/saved 展示历史记录列表，支持搜索和筛选
```

所有接口均返回 JSON，无需 session 认证（管理类设置接口除外）。
媒体文件通过 GET 直接访问，可用于 `ImageView`、`VideoView` 等组件加载。

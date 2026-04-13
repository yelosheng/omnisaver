<div align="center">
  <img src="telegram_avatar.png" alt="OmniSaver" width="120">
</div>

# OmniSaver — 多平台内容归档工具

专为 NAS、家庭服务器或树莓派设计的自托管内容保存工具。一键将推文、YouTube 视频、小红书笔记、微信公众号文章和任意网页（含图片和视频）存档到本地——无需 Twitter API 密钥。

![Python](https://img.shields.io/badge/Python-3.7%2B-blue) ![License](https://img.shields.io/badge/License-MIT-green) ![No API Key](https://img.shields.io/badge/Twitter%20API-不需要-brightgreen)

[English](README.md)

---

## ✨ 功能特性

- 自托管部署，可运行于任意 Linux 设备、NAS 或树莓派
- 无需 Twitter API 密钥，使用 Playwright 浏览器自动化抓取
- **多平台支持：**
  - **Twitter/X** —— 保存推文、完整串推、长文 Article 和视频
  - **Reddit** —— 保存帖子正文、图集、内嵌图片、视频和作者信息
  - **YouTube** —— 保存视频元数据、字幕和频道信息
  - **Bilibili (哔哩哔哩)** —— 保存视频元数据和高清视频文件
  - **快手 (Kuaishou)** —— 通过 Playwright 原生抓取视频（无需 Cookie）
  - **抖音 (Douyin) / TikTok** —— 通过 Playwright 原生抓取无水印视频（无需 Cookie）
  - **小红书（XHS）** —— 通过 Telegram 机器人或 REST API 保存图文帖和视频
  - **微信公众号** —— 保存文章全文、图片和排版
  - **任意网页** —— 类 Pocket 稍后阅读功能，支持任意 `http/https` URL；使用 Firefox 阅读模式算法（Mozilla Readability.js）提取正文和图片
- **完整串推抓取** —— 配置 Twitter 账号凭证后，自动获取整条回复链并将所有媒体内联嵌入存档
- **Twitter 长文 Article 支持** —— 自动检测并保存 `/status/` URL 下的长文全文内容
- **Twitter 视频下载** —— 通过 yt-dlp 下载视频；配置凭证后支持登录态下载
- **抖音原生抓取器** —— 使用 Playwright 绕过 API 限制，直接从页面提取原片地址并自动去除水印
- 统一 URL 输入 —— 在首页粘贴任意支持的链接，自动识别平台类型
- 油猴脚本为 Twitter/X 推文和 YouTube 视频页面/缩略图添加保存按钮
- 生成多格式内容文件：纯文本、Markdown、Reader-mode HTML
- 保存完整元数据（作者信息、发布时间等）为 JSON
- 内置任务队列与失败重试机制（指数退避）
- **手动重新下载** —— 支持在任务队列页面对任意任务执行“强制重新下载”操作
- Web UI 支持实时日志流、任务监控和内容浏览
- 已保存页面显示平台标识（X、YouTube、抖音、小红书、微信、🌐 网页）
- **YouTube 描述栏超链接自动转换** —— 视频描述中的纯文本链接在查看页面自动渲染为可点击的超链接
- **增强搜索：** 全文检索（含微信/网页文章标题）；支持按平台多选筛选、日期范围筛选（快捷预设或自定义区间）；各筛选条件可叠加
- 支持瀑布加载和分页两种浏览模式（可切换）
- 每条归档内容可生成唯一分享链接
- 支持在 Web UI 用户菜单直接修改密码
- 可选：Telegram 机器人——向私人 Bot 发送链接即可触发保存（支持所有平台）
- 可选：基于 Gemini API 的 AI 智能标签生成
- 可选：通过 FFmpeg 生成视频缩略图

---

## 🚀 快速开始

**前提条件：** Python 3.7+。

- **yt-dlp** —— Twitter/X 和小红书视频下载必需：`pip install yt-dlp` 或参考 [yt-dlp 安装说明](https://github.com/yt-dlp/yt-dlp#installation)
- **FFmpeg** —— 可选，用于生成视频缩略图

```bash
# 1. 克隆仓库
git clone https://github.com/yelosheng/omnisaver.git
cd omnisaver

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 安装 Playwright 浏览器（必需）
python -m playwright install chromium

# 4. 复制并编辑配置文件
cp config.ini.example config.ini
```

### 启动 Web 界面

```bash
python run_web.py
```

浏览器访问 `http://localhost:6201`，默认登录账号：`admin` / 密码：`admin`。

> **首次登录后请立即修改密码：** 点击右上角用户菜单 → **修改密码**。

### Docker 部署（推荐用于 NAS / 家庭服务器）

Docker 是最简单的部署方式，镜像已内置 yt-dlp 和 FFmpeg。

> 预构建镜像已发布到 Docker Hub，无需本地编译。
> `docker pull irritable0971/omnisaver:latest`

```bash
# 1. 克隆仓库
git clone https://github.com/yelosheng/omnisaver.git
cd omnisaver

# 2. 复制配置文件
cp config.ini.example config.ini

# 3. 构建并启动
docker compose up -d

# 4. 访问 http://localhost:6201
```

所有数据（数据库、已保存内容、用户信息）均存储在宿主机的 `./docker-data/` 目录中，容器重启或重建后数据不会丢失。

> **注意：** 首次构建需要几分钟——Playwright 下载 Chromium（约 200 MB），yt-dlp 也会在构建时获取。

**自定义端口或保存路径** —— 启动前编辑 `docker-compose.yml`：

```yaml
ports:
  - "8080:6201"                          # 左侧改为你想要的宿主机端口
volumes:
  - /mnt/nas/twitter:/app/saved_tweets   # 指向 NAS 或外部存储
```

---

## 🖱️ 浏览器插件（油猴脚本）——桌面端首选

桌面浏览器最便捷的保存方式。油猴脚本会在 Twitter/X 每条推文下方和 YouTube 视频页面注入**保存按钮**。在 YouTube 首页，鼠标悬停在视频缩略图上时会出现保存图标。点击即可归档，无需离开页面或手动复制链接。

<img src="X_page_tweet.png" alt="推文页面上的保存按钮" width="75%">

**安装步骤：**
1. 安装 [Tampermonkey](https://www.tampermonkey.net/) 浏览器扩展（支持 Chrome、Firefox、Edge、Safari）
2. 启动 Web 界面：`python run_web.py`
3. 访问 `http://localhost:6201/help`，点击安装链接——Tampermonkey 会弹出确认对话框
4. 点击**安装**——此后每条推文下方都会自动出现保存按钮

**配置后端地址**（首次使用或服务器地址变更时需要设置）：
- 点击浏览器工具栏中的 Tampermonkey 图标
- 找到 **Twitter/X Archiver Save Button** 脚本，点击设置图标
- 点击 **⚙️ 设置后端地址**，输入你的服务地址

如果服务器与浏览器在同一台设备上，默认的 `http://localhost:6201` 即可使用。如果部署在家庭服务器或 NAS 上，填入设备的局域网地址，例如 `http://192.168.1.100:6201`。

脚本文件位于 `tampermonkey/twitter-saver.user.js`。

---

## 🔑 Twitter/X 账号凭证（可选——启用完整串推抓取）

默认情况下，本工具使用 Playwright 浏览器自动化抓取。配置 Twitter Cookie 后可启用 **xreach**——速度更快的抓取方式，支持完整串推获取和登录态视频下载。

**配置后可解锁：**
- 完整串推抓取——将整条自回复链存为单一存档（含所有内联媒体）
- 通过 yt-dlp 的登录态视频下载
- 单条推文抓取速度提升

**配置步骤（通过 Web 界面）：**
1. 在浏览器中登录 [x.com](https://x.com)
2. 安装 [Cookie-Editor](https://cookie-editor.cgagnier.ca/) 浏览器扩展
3. 在 x.com 页面点击 Cookie-Editor 图标 → **Export** → **Export as JSON** → 复制
4. 在 Web 界面进入**设置** → **Twitter/X 凭证** → 粘贴 JSON → **保存**

工具会自动从 JSON 中提取 `auth_token` 和 `ct0` 并写入 `config.ini`，重启后凭证保留。

> **提示：** Twitter 会话通常在数周至数月后过期。如果串推抓取失效，重新导出 Cookie 并在设置页面粘贴即可。

---

## 👽 Reddit 凭证（可选，但推荐配置）

Reddit 帖子很多时候可以匿名抓取，但配置 Cookie 后，分享链接解析和媒体下载会稳定得多。

**配置 Reddit Cookie 的作用：**
- 将 `reddit.com/r/.../s/...` 分享链接解析为标准帖子链接
- 提高图片、图集和缩略图下载成功率
- 在 Reddit 限制匿名 JSON 访问时减少失败

**配置步骤（通过 Web 界面）：**
1. 在浏览器中登录 [reddit.com](https://www.reddit.com)
2. 安装 [Cookie-Editor](https://cookie-editor.cgagnier.ca/) 浏览器扩展
3. 在 reddit.com 页面点击 Cookie-Editor 图标 → **Export** → **Export as JSON** → 复制
4. 在 Web 界面进入 **设置** → **Reddit Cookie** → 粘贴 JSON → **保存**

导出的 Cookie 必须包含 `reddit_session`。程序会将其保存在本地 `~/.agent-reach/reddit/cookies.json`。

**可选 OAuth 兜底：** 如果你所在环境里 Reddit 开始拦匿名 JSON 接口，可在启动 OmniSaver 前设置环境变量 `REDDIT_CLIENT_ID` 和 `REDDIT_CLIENT_SECRET`。

---

## 📕 小红书（XiaoHongShu）集成

XHS 支持由 [agent-reach](https://github.com/Panniantong/agent-reach) 及其 `xiaohongshu-mcp` Docker 容器驱动。配置完成后，可通过 Telegram 机器人转发链接或调用 REST API 保存任意小红书笔记。

### 前提条件

- Docker
- Node.js（用于 `mcporter` 和通过 npm 安装的 `yt-dlp`）

### 配置步骤

**1. 安装 agent-reach**

```bash
npm install -g agent-reach
agent-reach install
```

**2. 启动小红书 MCP 服务器**

```bash
mkdir -p ~/.agent-reach/xhs
touch ~/.agent-reach/xhs/cookies.json
docker run -d --name xiaohongshu-mcp \
  -p 18060:18060 \
  -v ~/.agent-reach/xhs/cookies.json:/app/cookies.json \
  xpzouying/xiaohongshu-mcp
```

**3. 配置 Cookie（需要登录）**

在浏览器中登录 xiaohongshu.com，使用 [Cookie-Editor](https://cookie-editor.cgagnier.ca/) 导出 Cookie（JSON 格式），然后写入本地文件并同步至容器：

```bash
# 将导出的 JSON 写入本地
cat > ~/.agent-reach/xhs/cookies.json << 'EOF'
[ 粘贴 Cookie-Editor 导出的 JSON 数组 ]
EOF

# 同步至容器
cat ~/.agent-reach/xhs/cookies.json | docker exec -i xiaohongshu-mcp sh -c 'cat > /app/cookies.json'
docker restart xiaohongshu-mcp
```

**4. 注册 MCP 服务器**

在 `~/.mcporter/mcporter.json` 中添加：

```json
{
  "mcpServers": {
    "xiaohongshu": { "baseUrl": "http://localhost:18060/mcp" }
  }
}
```

**5. 验证**

```bash
mcporter call 'xiaohongshu.list_feeds()'
```

### 保存小红书笔记

**通过 Telegram 机器人** —— 转发或粘贴任意小红书链接，支持以下格式：
- 完整链接：`https://www.xiaohongshu.com/explore/<id>?xsec_token=...`
- App 分享文本：`标题~ http://xhslink.com/xxx 复制后打开【小红书】查看笔记！`（自动提取短链并跳转）

机器人会回复标题、类型、文件数量和 `/view/<slug>` 分享链接。

**通过 REST API：**

```bash
curl -X POST http://localhost:6201/api/submit/xhs \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.xiaohongshu.com/explore/<id>?xsec_token=<token>"}'
```

### 输出结构

```
saved_xhs/
└── 2024-01-15_笔记标题_feedid/
    ├── content.txt        # 纯文本描述
    ├── content.md         # 含作者信息和互动数据的 Markdown
    ├── metadata.json      # 完整 API 响应（不含评论）
    ├── avatar.jpg         # 作者头像
    ├── images/            # 图文帖：01.webp、02.webp……
    ├── videos/            # 视频帖：<标题>.mp4
    └── thumbnails/        # 视频封面图
```

### ⚠️ Cookie 使用须知

> **Cookie 会定期过期。** 小红书的 `web_session` Cookie 通常在 **7～30 天**后失效。一旦 XHS 调用开始报错（"Expecting value"），需要重新从浏览器导出 Cookie 并按步骤 3 更新。
>
> **频繁使用可延长有效期。** 如果启用了定时自动存档功能（每 30～60 分钟运行一次），会话往往能保持更长时间；长时间不使用则会更快过期。
>
> **Cookie 等同于账号凭证。** Cookie 文件包含完整的登录会话信息，请妥善保管，不要泄露给他人或提交至公开代码仓库。
>
> **本工具不会存储或上传你的 Cookie。** Cookie 仅保存在本地（`~/.agent-reach/xhs/cookies.json`）并注入 Docker 容器，不会被发送到任何第三方服务器。
>
> **小红书服务条款。** 使用本工具须符合小红书服务条款，仅限个人存档用途，不得用于批量采集或商业目的，以免账号被封禁。

---

## 🎬 YouTube 集成

保存 YouTube 视频的元数据、字幕和频道信息。

### 保存 YouTube 视频

**通过 Web UI** —— 在首页输入框粘贴任意 YouTube 链接。支持格式：
```
https://www.youtube.com/watch?v=VIDEO_ID
https://youtu.be/VIDEO_ID
https://www.youtube.com/shorts/VIDEO_ID
```

**通过油猴脚本** —— 在 YouTube 视频播放页面，操作栏中会出现保存按钮；在首页，鼠标悬停在视频缩略图上时左上角会出现保存图标。

**通过 Telegram 机器人** —— 发送或转发任意 YouTube 链接。

**通过 REST API：**
```bash
curl -X POST http://localhost:6201/api/submit/youtube \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=VIDEO_ID"}'
```

### YouTube 设置

在 Web UI 的 `/settings` 页面可配置 **YouTube Data API 密钥**（用于获取频道头像，可选）。前往 [Google Cloud Console](https://console.cloud.google.com) → 启用「YouTube Data API v3」→ 凭据 → API 密钥，免费获取。

---

## 🌐 网页稍后阅读

将任意文章或网页保存为离线副本——类似 Pocket 或 Instapaper 的效果。

### 保存网页

**通过 Web UI** —— 在首页输入框粘贴任意 `http://` 或 `https://` 链接。

**通过 Telegram 机器人** —— 发送任意非小红书/微信/YouTube/Twitter 的网页链接。

**通过 REST API：**
```bash
curl -X POST http://localhost:6201/api/submit \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article"}'
```

### 工作原理

使用 Playwright 渲染完整页面（执行 JavaScript、触发懒加载图片），再运行 **Mozilla Readability.js**（与 Firefox 阅读模式相同的算法）提取干净的正文内容，并将图片下载到本地。

### 输出结构

```
saved_tweets/
└── YYYY/MM/YYYY-MM-DD_标题_hash/
    ├── content.html       # 阅读模式 HTML（含内联图片）
    ├── content.txt        # 纯文本
    ├── content.md         # Markdown（含元数据头部）
    ├── metadata.json      # 标题、作者、来源站点、发布日期、原文链接
    └── images/            # 下载的图片
```

---

## 📰 微信公众号集成

保存微信公众号文章的全文、图片和排版。

### 保存微信文章

**通过 Web UI** —— 在首页输入框粘贴任意微信文章链接。

**通过 Telegram 机器人** —— 发送或转发任意 `mp.weixin.qq.com` 链接。

**通过 REST API：**
```bash
curl -X POST http://localhost:6201/api/submit/wechat \
  -H "Content-Type: application/json" \
  -d '{"url": "https://mp.weixin.qq.com/s/ARTICLE_ID"}'
```

### 输出结构

```
saved_wechat/
└── YYYY/MM/YYYY-MM-DD_article_id/
    ├── content.txt        # 纯文本
    ├── content.md         # Markdown（含标题、作者、发布时间）
    ├── metadata.json      # 文章元数据
    ├── images/            # 文章内嵌图片
    └── videos/            # 内嵌视频（如有）
```

---

## 🤖 Telegram 机器人——移动端首选

手机或平板上最便捷的保存方式。通过 Twitter/X 原生分享功能，直接将推文分享给你的私人 Telegram 机器人，无需复制链接，无需切换 App。

<img src="telegram_bot.png" alt="Telegram 机器人保存推文" width="50%">

**配置步骤：**
1. 在 Telegram 中打开 [@BotFather](https://t.me/BotFather)，发送 `/newbot`，按提示操作，复制机器人 Token
2. 在 Web 界面访问 `/telegram`，粘贴 Token，点击**保存并启动机器人**
3. 在 Telegram 中打开你的机器人，发送 `/start`——第一个发送此命令的人成为永久所有者，只有所有者可以触发保存
4. 完成设置——向机器人发送或转发任意 `twitter.com` / `x.com` 链接，机器人会立即回复任务 ID 并开始下载

**移动端使用方法（主要场景）：**
1. 在 Twitter/X App 中打开任意推文
2. 点击**分享**图标 → **分享至...** → 从联系人列表中选择你的 Telegram 机器人
3. 机器人收到链接后立即加入队列，并发送确认回复

**机器人指令：**
- 包含 Twitter/X 链接的消息 → 加入保存队列
- 包含 YouTube 链接的消息 → 加入保存队列
- 包含小红书链接的消息 → 立即保存（参见小红书章节）
- 包含微信文章链接的消息 → 加入保存队列
- 其他任意 `http/https` 链接 → 作为网页稍后阅读任务加入队列
- `/status` — 显示当前队列大小

---

## ⚙️ 配置说明

将 `config.ini.example` 复制为 `config.ini` 并按需修改。

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `[storage] base_path` | 推文保存路径 | `./saved_tweets` |
| `[storage] create_date_folders` | 按日期创建子文件夹 | `true` |
| `[download] max_retries` | 下载失败最大重试次数 | `3` |
| `[download] timeout_seconds` | 请求超时时间（秒） | `30` |
| `[scraper] use_playwright` | 使用 Playwright 浏览器自动化（推荐） | `true` |
| `[scraper] headless` | 无头模式运行浏览器 | `true` |
| `[scraper] debug_mode` | 调试模式，出错时保存截图 | `false` |
| `[twitter] auth_token` | Twitter `auth_token` Cookie（可选，启用 xreach 串推抓取） | 未设置 |
| `[twitter] ct0` | Twitter `ct0` Cookie（需与 `auth_token` 同时设置） | 未设置 |
| `[ai] gemini_api_key` | Gemini API 密钥（可选，用于 AI 标签） | 未设置 |
| `[ai] youtube_api_key` | YouTube Data API v3 密钥（可选，用于频道头像） | 未设置 |
| `[telegram] bot_token` | Telegram 机器人令牌（可选，用于 Telegram 集成） | 未设置 |

**环境变量覆盖：**

| 环境变量 | 说明 |
|---|---|
| `SAVE_PATH` | 覆盖保存路径 |
| `USE_PLAYWRIGHT` | 覆盖 Playwright 开关 |
| `PLAYWRIGHT_HEADLESS` | 覆盖无头模式 |
| `PLAYWRIGHT_DEBUG` | 设为 `true` 启用调试截图 |
| `SSL_CERT_PATH` / `SSL_KEY_PATH` | 启用 HTTPS |

---

## 📖 使用方法

### Web 界面

启动后访问 `http://localhost:6201`：

| 页面 | 功能 |
|---|---|
| `/` | 提交任意支持的 URL 开始归档（自动识别平台） |
| `/tasks` | 查看任务队列状态 |
| `/saved` | 浏览和搜索已归档内容（Twitter、YouTube、小红书、微信、网页） |
| `/tags` | 管理 AI 生成的标签 |
| `/retries` | 查看失败任务并手动重试 |
| `/view/<slug>` | 通过分享链接查看归档内容 |
| `/debug` | 系统状态和卡死任务重置 |
| `/telegram` | Telegram 机器人配置 |
| `/settings` | YouTube API 密钥和小红书自动存档设置 |
| `/help` | 油猴脚本安装说明 |

### 命令行

```bash
# 归档单条推文
python main.py https://x.com/username/status/1234567890

# 跳过媒体下载
python main.py https://x.com/username/status/1234567890 --no-media

# 指定输出目录
python main.py https://x.com/username/status/1234567890 --output /path/to/save

# 显示详细输出
python main.py https://x.com/username/status/1234567890 --verbose
```

**支持的 URL 格式：**

```
https://twitter.com/username/status/1234567890
https://x.com/username/status/1234567890
https://mobile.twitter.com/username/status/1234567890
https://m.twitter.com/username/status/1234567890
```

---

## 📁 输出结构

```
saved_tweets/
└── 2024-01-15_1234567890123456789/
    ├── content.txt        # 推文纯文本
    ├── content.html       # Reader-mode HTML
    ├── content.md         # Markdown 格式
    ├── metadata.json      # 完整元数据（作者、时间等）
    ├── avatar.jpg         # 作者头像
    ├── images/
    ├── videos/
    └── thumbnails/        # 视频缩略图（需 FFmpeg）
```

---

## 🏷️ AI 标签功能（可选）

归档成功后可自动为推文生成语义标签，帮助分类和检索。生成方法按优先级排列：

1. **Gemini API** — 在 `config.ini` 中设置 `gemini_api_key`（推荐，免费额度充足）。
2. **规则匹配** — 无需 API 密钥，基于内置关键词规则自动生成基础标签。

通过 Web 界面的 `/tags` 页面可管理所有标签，也可在 `/saved` 页面对单条内容手动触发标签生成。

---

## 🔧 故障排除

**推文无法找到** — 推文可能已被删除或设为私有，请检查 URL 是否正确，并确认该推文在浏览器中可以正常访问。

**Playwright 浏览器未安装** — 运行 `python -m playwright install chromium`。

**网络连接问题** — 检查网络连接和防火墙设置。如果所在地区访问 Twitter/X 受限，需要配置代理后再使用本工具。

**文件权限错误** — 确认对 `base_path` 所指向的目录有写入权限，并检查磁盘剩余空间。

**任务卡死不动** — 访问 Web 界面的 `/debug` 页面，使用「重置卡死任务」功能。

**启用调试模式** — 在 `config.ini` 中设置 `debug_mode = true`，或设置环境变量 `PLAYWRIGHT_DEBUG=true`，出错时会自动保存浏览器截图至项目根目录。

---

## ⚠️ 免责声明

- **仅供个人存档使用。** 本工具设计用途为个人保存公开内容，供离线阅读和个人研究。
- **请遵守 Twitter/X 服务条款。** 使用本工具须符合 [Twitter/X 服务条款](https://twitter.com/en/tos)。用户对自身的使用行为及其法律合规性承担全部责任。
- **请遵守小红书服务条款。** 使用小红书集成功能须符合小红书用户协议，仅限个人存档用途。
- **禁止商业用途和大规模抓取。** 本工具不得用于商业目的、批量数据采集、训练机器学习模型或任何形式的大规模抓取行为。
- **尊重他人版权。** 内容的版权归原作者所有，请勿在未经授权的情况下转载、分发或二次利用他人内容。
- **Cookie 安全。** 使用小红书功能需要提供浏览器 Cookie，这等同于你的账号登录凭证。请妥善保管，不要分享给他人或提交至任何公开仓库。
- **作者不对滥用行为负责。** 本项目作者不对任何因滥用本工具而产生的法律问题、账号封禁或其他后果承担责任。

---

## 📄 License

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

---

## 🤝 贡献

欢迎通过 GitHub Issues 报告问题或提出功能建议，也欢迎提交 Pull Request。提交前请确保现有测试通过：

```bash
python -m pytest tests/
```

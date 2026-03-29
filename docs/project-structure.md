# OmniSaver 项目结构

```
twitter_collector/
│
├── app.py                        # Flask 主应用（~2200行）：所有路由、SQLite初始化/迁移、
│                                 # 后台任务队列、重试逻辑、标签生成、媒体服务
├── run_web.py                    # Web 启动入口：初始化DB/服务/后台线程，启动Telegram Bot，
│                                 # 最终调用 app.run()
├── main.py                       # CLI 入口：命令行方式提交URL，用 rich 显示进度
│
├── requirements.txt              # Python 依赖包列表
├── config.ini                    # 运行时配置（gitignored）：存储路径、API Key、
│                                 # Playwright设置等
├── config.ini.example            # 配置文件模板，提交到 git 供参考
├── twitter_saver.db              # SQLite 主数据库（gitignored）：任务、标签、FTS索引
├── users.json                    # 用户账号数据（gitignored）：用户名+SHA256密码哈希
├── secret_key.txt                # Flask session 密钥（gitignored）：持久化保证重启不掉登录
├── telegram_owner.json           # Telegram Bot 主人的 chat_id（gitignored）
│
├── models/                       # 数据模型（dataclass）
│   ├── tweet.py                  # Tweet dataclass：id、text、html_content、author、
│   │                             # media_urls/types、reply_to、conversation_id 等字段
│   └── media_file.py             # MediaFile dataclass：媒体文件元信息
│
├── services/                     # 业务服务层
│   ├── config_manager.py         # 加载 config.ini 和环境变量，校验配置，提供 get_save_path()
│   ├── file_manager.py           # 文件读写：按日期建目录、写 content.txt/metadata.json 等
│   ├── media_downloader.py       # 并行下载图片/视频，写入 images/ videos/ 目录
│   ├── playwright_scraper.py     # 主力抓取器：Chromium 浏览器自动化，反检测（随机UA/viewport）
│   ├── web_scraper.py            # 备用抓取器：requests + BeautifulSoup 静态页面解析
│   ├── twitter_service.py        # Twitter/X 抓取编排：调用 scraper + xreach + 文件保存
│   ├── xhs_service.py            # 小红书下载：调用 mcporter npm 工具
│   ├── wechat_service.py         # 微信公众号抓取：调用 wechat-article-for-ai Python工具
│   ├── youtube_service.py        # YouTube 下载：yt-dlp 下载视频，获取字幕和频道头像
│   ├── webpage_service.py        # 通用网页抓取：提取 Reader 模式 HTML 和 Markdown
│   ├── telegram_bot.py           # Telegram Bot 守护线程：首个 /start 用户成为 owner，
│   │                             # 接收消息后调用 submit_callback 提交任务
│   ├── tag_generator.py          # 标签自动生成：规则匹配 → Gemini API → Claude API，
│   │                             # prompt 配置在 prompts.ini
│   ├── user_manager.py           # 用户登录/密码管理：SHA-256+salt，数据存 users.json
│   └── Readability.js            # Mozilla Readability.js：提取网页 Reader 模式正文
│
├── utils/                        # 工具函数
│   ├── url_parser.py             # Twitter URL 解析和推文 ID 提取
│   ├── html_to_markdown.py       # HTML→Markdown 转换；extract_readable_content() 提取正文
│   └── realtime_logger.py        # 内存日志缓冲 + SSE 流式推送至 /api/logs/stream
│
├── templates/                    # Jinja2 HTML 模板
│   ├── base.html                 # 基础模板：导航栏、Bootstrap、全局样式
│   ├── login.html                # 登录页
│   ├── index.html                # 首页：提交 URL 输入框
│   ├── saved.html                # 已保存内容列表：无限滚动/分页切换、搜索、平台筛选
│   ├── tweet_display.html        # 内容详情页（/view/<slug>）：渲染各平台内容+媒体
│   ├── tasks.html                # 任务队列监控页
│   ├── retries.html              # 失败任务重试管理页
│   ├── settings.html             # 统一设置页：XHS Cookie、YouTube API Key 等
│   ├── telegram.html             # Telegram Bot 配置页
│   ├── debug.html                # 调试页：系统状态、卡住任务重置
│   ├── help.html                 # 帮助页：Tampermonkey 脚本安装说明
│   ├── change_password.html      # 修改密码页
│   ├── xhs_settings.html         # 小红书专项设置（Cookie 等）
│   ├── view_tweet.html           # 旧版推文预览模板（已被 tweet_display.html 取代）
│   └── view_tweet_simple.html    # 旧版简化推文预览模板
│
├── static/                       # 静态资源
│   ├── favicon.svg               # 网站 favicon（SVG）
│   ├── icon-128.png              # 应用图标 128×128
│   └── xhs.ico                  # 小红书平台图标（用于 saved 页面平台标识）
│
├── tampermonkey/
│   └── twitter-saver.user.js     # Tampermonkey 浏览器脚本：在 X/Twitter 页面注入
│                                 # "Save" 按钮，通过 GM_setValue 配置后端地址
│
├── tools/                        # 运维/维护脚本（手动执行）
│   ├── change_password.py        # 命令行修改 Web UI 登录密码
│   ├── clear_all_data.py         # 清空全部已保存数据和数据库记录
│   ├── generate_missing_thumbnails.py  # 为缺失缩略图的视频用 FFmpeg 补生成
│   ├── migrate_to_hierarchical.py      # 将旧平铺目录结构迁移为 YYYY/MM/ 层级结构
│   ├── regenerate_content.py     # 从 metadata.json 重新生成 content.html
│   └── test_login.py             # 测试登录接口的简单脚本
│
├── tests/                        # 自动化测试
│   ├── test_config_manager.py    # ConfigManager 单元测试
│   ├── test_file_manager.py      # FileManager 单元测试
│   ├── test_media_downloader.py  # MediaDownloader 单元测试
│   ├── test_twitter_service.py   # TwitterService 单元测试
│   ├── test_url_parser.py        # URL 解析器单元测试
│   └── test_integration.py       # 集成测试
│
├── docs/                         # 文档
│   ├── API.md                    # REST API 接口文档（供第三方/移动端接入）
│   └── project-structure.md      # 本文件：项目结构说明
│
├── Dockerfile                    # Docker 镜像构建：python:3.11-slim + Playwright Chromium
│                                 # + Node.js + xreach-cli + mcporter + wechat-article-for-ai
├── docker-compose.yml            # Docker Compose：omnisaver 主服务 + init 初始化服务，
│                                 # 数据持久化至 ./docker-data/
├── docker-mcporter.json          # 容器内 mcporter 的 MCP 服务器配置
├── .dockerignore                 # Docker 构建忽略规则
│
├── README.md                     # 英文说明文档
├── README.zh-CN.md               # 中文说明文档
├── LICENSE                       # MIT 开源协议
├── CLAUDE.md                     # Claude Code 项目级提示词（gitignored）
├── .gitignore                    # Git 忽略规则
├── .github/
│   └── copilot-instructions.md  # GitHub Copilot 项目级指令
│
├── telegram_avatar.png           # 项目 Logo（README 顶部展示 + Telegram Bot 头像）
├── telegram_bot.png              # README 中 Telegram Bot 功能截图
├── X_page_tweet.png              # README 中 Tampermonkey 功能截图
│
└── venv/                         # Python 虚拟环境（gitignored）
```

## 运行时生成（gitignored，不在仓库中）

```
twitter_collector/
├── twitter_saver.db              # SQLite 主数据库
├── users.json                    # 用户账号
├── secret_key.txt                # Flask session 密钥
├── telegram_owner.json           # Telegram Bot owner
├── config.ini                    # 实际配置文件
└── docker-data/                  # Docker 部署时的持久化数据目录
    ├── twitter_saver.db
    ├── users.json
    ├── secret_key.txt
    ├── telegram_owner.json
    └── saved_*/                  # 各平台保存的内容
```

## 各平台保存目录结构

```
<base_path>/
├── saved_tweets/YYYY/MM/YYYY-MM-DD_<tweet_id>/
├── saved_xhs/YYYY-MM-DD_<title>_<id>/
├── saved_wechat/YYYY-MM-DD_<title>_<id>/
└── saved_youtube/YYYY-MM-DD_<title>_<id>/

每个目录内包含：
├── content.txt       # 纯文本内容
├── content.html      # Reader 模式 HTML（部分平台）
├── content.md        # Markdown 格式（XHS / WeChat / YouTube）
├── metadata.json     # 元数据（标题、作者、时间、平台信息等）
├── avatar.jpg        # 作者头像
├── images/           # 下载的图片
├── videos/           # 下载的视频
└── thumbnails/       # 视频缩略图（FFmpeg 生成）
```

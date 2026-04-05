# OmniSaver 项目结构

```
twitter_collector/
│
├── app.py                        # Flask 主应用（~2500行）：所有路由、认证、模板过滤器、
│                                 # init_services()、媒体服务。不含业务逻辑（已拆分到 services/）
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
│   ├── db.py                     # 数据库层：get_db_connection、init_db、rebuild_fts_index、
│   │                             # FTS工具函数、路径/时间工具、get_setting/set_setting
│   ├── background.py             # 后台层：任务队列、8个任务处理器（tweet/xhs/wechat/
│   │                             # youtube/douyin/weibo/bilibili/webpage）、重试调度、
│   │                             # init_background() 注入服务依赖
│   ├── config_manager.py         # 加载 config.ini 和环境变量，校验配置，提供 get_save_path()
│   ├── file_manager.py           # 文件读写：按日期建目录、写 content.txt/metadata.json 等
│   ├── media_downloader.py       # 并行下载图片/视频，写入 images/ videos/ 目录
│   ├── playwright_scraper.py     # 主力抓取器：Chromium 浏览器自动化，反检测（随机UA/viewport）
│   ├── web_scraper.py            # 备用抓取器：requests + BeautifulSoup 静态页面解析
│   ├── twitter_service.py        # Twitter/X 抓取编排：调用 scraper + xreach + 文件保存
│   ├── xhs_service.py            # 小红书下载：调用 mcporter npm 工具
│   ├── wechat_service.py         # 微信公众号抓取：调用 wechat-article-for-ai Python工具
│   ├── youtube_service.py        # YouTube 下载：yt-dlp 下载视频，获取字幕和频道头像
│   ├── douyin_service.py         # 抖音下载：Playwright 模拟移动端抓取无水印视频
│   ├── weibo_service.py          # 微博下载：Playwright 抓取正文（含长文）、图片和视频
│   ├── bilibili_service.py       # Bilibili 下载：yt-dlp 获取视频，Playwright 获取头像
│   ├── kuaishou_service.py       # 快手下载：Playwright 拦截真实流地址和元数据
│   ├── instagram_service.py      # Instagram 下载：yt-dlp 与 Playwright Embed Fallback 双重保障
│   ├── webpage_service.py        # 通用网页抓取：提取 Reader 模式 HTML 和 Markdown
│   ├── telegram_bot.py           # Telegram Bot 守护线程：接收消息后自动提取 URL 并提交任务
│   ├── tag_generator.py          # 标签自动生成：规则匹配 → Gemini API
│   ├── user_manager.py           # 用户登录/密码管理：SHA-256+salt，数据存 users.json
│   └── Readability.js            # Mozilla Readability.js：提取网页 Reader 模式正文
│
├── utils/                        # 工具函数
│   ├── url_parser.py             # 平台 URL 解析和合法性校验
│   ├── html_to_markdown.py       # HTML→Markdown 转换
│   └── realtime_logger.py        # 内存日志缓冲 + SSE 流式推送至前端
│
├── templates/                    # Jinja2 HTML 模板
│   ├── base.html                 # 基础模板：导航栏、Bootstrap、全局样式
│   ├── login.html                # 登录页
│   ├── index.html                # 首页：提交 URL 输入框
│   ├── saved.html                # 已保存内容列表：搜索、多平台筛选、视图切换
│   ├── tweet_display.html        # 内容详情页：适配各平台 Markdown 和媒体展示
│   ├── tasks.html                # 任务队列监控页：含强制重新下载功能
│   ├── retries.html              # 失败任务重试管理页
│   ├── settings.html             # 统一设置页
│   ├── telegram.html             # Telegram Bot 配置页
│   ├── debug.html                # 调试页：系统状态、卡住任务重置
│   ├── help.html                 # 帮助页：插件安装说明
│   └── change_password.html      # 修改密码页
│
├── static/                       # 静态资源
│   ├── favicon.svg               # 网站 favicon
│   ├── icon-128.png              # 应用图标
│   └── xhs.ico                  # 小红书平台图标
│
├── tampermonkey/
│   └── twitter-saver.user.js     # 浏览器脚本：在各平台页面注入保存按钮
│
├── tools/                        # 运维/维护脚本
│   ├── change_password.py        # 命令行修改密码
│   ├── clear_all_data.py         # 清空数据
│   ├── generate_missing_thumbnails.py  # 补生成视频缩略图
│   ├── migrate_to_hierarchical.py      # 目录结构迁移
│   └── regenerate_content.py     # 重新生成存档内容
│
├── tests/                        # 自动化测试
│   └── ...
│
├── docs/                         # 文档
│   ├── API.md                    # REST API 接口文档
│   ├── adding-new-platform.md    # 开发指南：如何新增平台
│   ├── project-structure.md      # 本文件：项目结构说明
│   └── plans/                    # 历史开发计划和设计文档
│
├── Dockerfile                    # Docker 镜像构建
├── docker-compose.yml            # Docker Compose 部署配置
├── README.md                     # 说明文档
└── LICENSE                       # MIT 许可证
```

## 服务层依赖关系

```
services/db.py
    ↑ 无内部依赖，只用标准库

services/background.py
    ↑ 依赖 services/db.py
    ↑ 通过 init_background() 注入各平台 Service 依赖

app.py
    ↑ 依赖 services/db.py、services/background.py
    ↑ 只含 Flask 路由逻辑
```

## 各平台保存目录结构

```
<base_path>/
├── saved_tweets/YYYY/MM/YYYY-MM-DD_<tweet_id>/
├── saved_douyin/YYYY-MM/YYYY-MM-DD_<title>_<id>/
├── saved_weibo/YYYY-MM/YYYY-MM-DD_<title>_<id>/
├── saved_bilibili/YYYY-MM/YYYY-MM-DD_<title>_<id>/
├── saved_kuaishou/YYYY-MM/YYYY-MM-DD_<title>_<id>/
├── saved_instagram/YYYY-MM/YYYY-MM-DD_<title>_<id>/
├── saved_xhs/YYYY/MM/YYYY-MM-DD_<id>/
├── saved_wechat/YYYY/MM/YYYY-MM-DD_<id>/
└── saved_youtube/YYYY-MM-DD_<title>_<id>/

每个目录内通常包含：
├── content.txt       # 纯文本描述
├── content.md        # 结构化 Markdown 存档
├── metadata.json     # 完整原始元数据
├── avatar.jpg        # 发布者头像
├── images/           # 图片资源
├── videos/           # 视频文件
└── thumbnails/       # 视频封面图
```

# OmniSaver 前端改进 Todo List

> 创建日期：2026-04-16
> 参考审查报告：`docs/frontend-audit-2026-04.md`

---

## 一、导航栏重组（高优先级）

- [ ] **精简主导航**：顺序调整为 `Status | Saved | Queue`，移除 `Search / Debug / Script / Telegram`
- [ ] **导航栏右侧增加「+ Save」按钮**：位于语言切换和用户菜单左侧，实心主题色样式，点击弹出 Modal 输入 URL 提交保存，全局可用，替代原来的独立提交页

---

## 二、页面结构调整（高优先级）

- [ ] **废弃独立的提交页**：移除旧的 `/status` 提交表单（`index.html`），`/` 改为重定向到 `/saved`
- [ ] **新建状态页** `/status`：只读健康仪表板，详见下方「状态页内容规划」
- [ ] **合并 `/saved` 和 `/search`**：`/saved` 顶部加搜索框 + 「筛选」按钮，点击展开高级筛选面板（平台多选、日期快捷按钮、自定义日期范围），默认收起保持页面简洁；废弃独立的 `/search` 路由，保留 `/search` → `/saved` 重定向
- [ ] **废弃独立的 `/telegram` 路由**：功能并入 Settings，保留 `/telegram` → `/settings` 重定向

---

## 三、新状态页内容规划

新的 `/status` 页面定位：**只读、只看健康情况、一眼知道系统是否正常运转**，不做任何配置操作。

### 需要显示的内容

- **后台服务健康**
  - 后台 Worker 线程是否在运行
  - 任务队列是否正常消化（是否卡住）

- **队列摘要**
  - Pending / Processing / Completed / Failed 各有多少（可点击跳转到 `/tasks` 对应过滤）

- **平台凭证状态**
  - 各平台 Cookie / Token：是否配置、是否有效（有效 / 过期 / 未配置）
  - 涵盖：XHS Cookie、Telegram Bot、YouTube API Key 等
  - 只显示状态，点击跳转到 Settings 修改

- **存储状态**
  - 保存路径是否可访问
  - 磁盘剩余空间

### 不放在状态页的内容

| 内容 | 已在 |
|------|------|
| 实时日志 | Settings → Advanced |
| 单条任务管理（重试/删除） | Tasks 页 |
| Cookie 配置修改 | Settings → Platforms |
| 最近保存的内容 | Saved 页 |

---

## 四、Settings 页面重构（高优先级）

Settings 改为**左侧竖向 Tab 导航**布局，分四个分区：

| Tab | 内容 |
|-----|------|
| **General** | 保存路径、重试次数、超时、Playwright 模式等系统参数 |
| **Platforms** | 各平台 Cookie / Token（XHS、Twitter、Facebook、Reddit 等）+ YouTube API Key |
| **Connections** | Telegram Bot 配置、Browser Extension 安装说明、OmniSaver API Key |
| **Advanced** | Debug 日志查看器、重置卡住任务、强制启动队列等开发者工具 |

- [ ] **实现左侧竖向 Tab 布局**（移动端折叠为顶部横向 Tab）
- [ ] **General Tab**：迁移现有系统配置内容
- [ ] **Platforms Tab**：迁移各平台 Cookie/Token 配置，含 YouTube API Key
- [ ] **Connections Tab**：迁移 Telegram Bot 配置 + Browser Extension 安装说明（原 `/help` 页内容）+ OmniSaver API Key
- [ ] **Advanced Tab**：嵌入 Debug 日志查看器，保留重置卡住任务、强制启动队列等工具按钮
- [ ] **删除 Coming Soon 的 App 占位内容**：移除 App Store / Google Play 按钮和移动端广告区块

---

## 五、国际化补全（中优先级）

- [ ] 清除 `help.html` 里的硬编码中文字符串（"保存视频"、"设置后端地址"、"原创" 等）
- [ ] 将 `settings.html` / `telegram.html` 的硬编码英文字符串移入翻译文件

---

## 六、交互细节打磨（低优先级）

- [ ] **统计卡片加 hover 效果**：状态页的队列数字卡片加 `cursor: pointer` 和 hover 背景色
- [ ] **视图切换按钮加 active 状态**：`/saved` 的无限滚动 / 分页图标按钮，当前激活的加高亮样式
- [ ] **Debug 日志加颜色区分**：ERROR 红色、WARN 黄色、SUCCESS 绿色、INFO 默认色
- [ ] **错误 Modal 修复溢出**：`tasks.html` 的错误详情 `<pre>` 加 `white-space: pre-wrap; word-break: break-all`

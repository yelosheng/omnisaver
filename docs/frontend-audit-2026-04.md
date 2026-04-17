# OmniSaver 前端深度审查报告

> 审查日期：2026-04-16
> 改进计划见：`docs/frontend-todo.md`

---

## 一、信息架构问题

### 1. `/status` 页面定位混乱

**现状**：路由 `/status` 实际上是一个 URL 提交表单页，附带任务统计卡片和功能介绍，既不是真正的状态页，也不适合作为首页。

**决策**：
- 将 URL 提交功能移至导航栏右侧「+ Save」按钮（点击弹出 Modal）
- `/status` 改造为真正的只读健康仪表板，显示：后台服务状态、队列摘要、各平台凭证有效性、存储状态

---

### 2. `/saved` 和 `/search` 高度重复

**现状**：两个页面几乎一模一样（相同的平台过滤器、卡片布局、无限滚动），唯一区别是 `/search` 需要输入关键词才显示结果。用户无法理解为何有两个入口。

**决策**：
- 合并为 `/saved` 单一页面
- 顶部加搜索框 + 「筛选」按钮，点击展开高级筛选面板（平台多选、日期快捷按钮、自定义日期范围），默认收起
- 废弃 `/search` 路由，保留重定向

---

### 3. 导航栏条目过多，层级扁平

**现状**：8 个条目全部平铺：`Status | Queue | Saved | Search | Debug | Script | Telegram | Settings`，开发者工具和普通功能混杂，干扰主流程。

**决策**：
- 主导航精简为 3 项：`Status | Saved | Queue`
- 导航栏右侧固定区域：`[搜索框] [+ Save] [语言] [用户▼]`
- `Debug`、`Script`、`Telegram` 全部移入 Settings 页对应 Tab

---

## 二、路由与导航调整

| 当前路由 | 问题 | 决策 |
|----------|------|------|
| `/status` | 实为提交页，命名误导 | 改造为只读健康仪表板 |
| `/search` | 与 `/saved` 高度重复 | 废弃，功能并入 `/saved`，保留重定向 |
| `/telegram` | 独立页但本质是配置项 | 废弃，并入 Settings → Connections Tab，保留重定向 |
| `/help` / `/script` | 双路由指向同一页，且在主导航占位 | 移入 Settings → Connections Tab |
| `/debug` | 开发者工具出现在主导航 | 移入 Settings → Advanced Tab |

---

## 三、Settings 页面过于臃肿

**现状**：单一超长页面混合了系统配置、平台凭证、API Key、移动 App 占位广告，用户难以定位目标配置项。

**决策**：改为**左侧竖向 Tab 导航**布局（移动端折叠为顶部横向 Tab），分四个 Tab：

| Tab | 内容 |
|-----|------|
| **General** | 保存路径、重试次数、超时、Playwright 模式等系统参数 |
| **Platforms** | 各平台 Cookie / Token（XHS、Twitter、Facebook 等）+ YouTube API Key |
| **Connections** | Telegram Bot 配置、Browser Extension 安装说明、OmniSaver API Key |
| **Advanced** | Debug 日志查看器、重置卡住任务、强制启动队列等开发者工具 |

另：删除 Coming Soon 的 App Store / Google Play 占位内容。

---

## 四、视觉/交互细节问题

以下问题尚未处理，需在改版中一并修复：

### 1. 状态卡片无点击反馈
状态页的队列统计卡片可点击跳转到 `/tasks` 对应过滤，但缺少 `cursor: pointer` 和 hover 效果，用户无法发现可点击。

### 3. 视图切换按钮无激活状态
`/saved` 的无限滚动 / 分页切换图标缺少 active 状态高亮，用户无法判断当前模式。

### 4. Debug 日志无颜色区分
有 ERROR / WARN / INFO 等级别过滤按钮，但日志内容统一显示绿色，不同级别无颜色区分，过滤前无法快速定位问题。

### 5. 错误 Modal 可能溢出
`/tasks` 的错误详情用 `<pre>` 渲染，长行不换行，可能出现横向滚动条。需加 `white-space: pre-wrap; word-break: break-all`。

---

## 五、国际化不完整

`help.html` 混有硬编码中文字符串（"保存视频"、"设置后端地址"、"原创"等），在英文界面下直接显示。`settings.html` 和 `telegram.html` 也有未纳入翻译体系的硬编码英文字符串。

---

## 六、总结

应用视觉质量整体不错，Bootstrap 5 使用规范，色彩和间距合理。核心问题在于**信息架构**：功能随平台增加而堆叠，缺乏整体规划，导致导航命名混乱、页面职责重叠。

本次改版核心方向：
- URL 提交从独立页面变为全局 Modal 按钮
- `/status` 还原为真正的健康仪表板
- `/saved` 吸收搜索功能，成为内容管理的唯一入口
- Settings 从长页改为分 Tab 的结构化配置中心，同时承接 Telegram、Debug、Script 的功能

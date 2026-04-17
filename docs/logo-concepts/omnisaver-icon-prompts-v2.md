# OmniSaver Icon Generation Prompts v2

## 项目核心

**OmniSaver** 是一个多平台内容归档工具：
- 支持 Twitter/X、YouTube、小红书、微信、飞书、Reddit、Pinterest 等主流平台
- 无需任何平台 API Key，通过浏览器自动化抓取
- 内容永久保存到本地（文字、图片、视频、元数据）
- 提供 Web 界面和 CLI，用户完全掌控自己的数据

**核心主旨：把互联网上任何地方的内容，一键捕获并永久保存到你自己的地方。**

---

## 提示词

### Prompt 1 — 数字捕网
```
App icon for "OmniSaver", a universal content archiving tool that saves posts from any website to local storage.
Central concept: a glowing digital net or web pulling content inward from all directions.
A circular net pattern, threads converging to a bright center core that looks like a compact hard drive or archive box.
Deep dark blue background #0d1117. Net lines in electric teal #00d4aa. Center glow in warm white.
Ultra-clean flat vector, no text, scalable icon, 1:1 ratio. Professional developer tool aesthetic.
```

---

### Prompt 2 — 万能漏斗
```
Minimalist app icon representing "collect everything from the internet and store it locally".
A bold downward-pointing funnel shape. The wide top of the funnel shows tiny colorful dots or fragments
(representing different platforms and content types) flowing in. The narrow bottom feeds into
a solid cylindrical database stack.
Dark background #111827. Funnel in gradient from indigo #6366f1 to cyan #06b6d4.
Database icon in clean white. Flat geometric vector, high contrast, no text.
Suitable for a developer tool or productivity app.
```

---

### Prompt 3 — 轨道汇聚
```
App icon for a multi-platform content collector. Abstract symbol showing multiple orbiting paths
converging into a single central storage point — like satellites or data packets being pulled
into a gravity well.
Five circular orbit arcs in different accent colors (red, orange, green, blue, purple)
all spiraling inward toward a bright white core node.
Very dark navy background, thin crisp orbital lines, glowing center.
Flat vector style with subtle depth, no text, 1:1 square canvas, modern tech icon.
```

---

### Prompt 4 — 磁力存储
```
Bold, iconic app logo for a universal web content archiving tool called OmniSaver.
Design: a strong downward arrow, thick and geometric, made up of small colorful tiles or pixels
(each tile a different platform color: red, blue, green, orange, purple).
The arrow points into a clean rectangular container/box at the bottom, representing local storage.
White or very light gray background. Sharp vector shapes, vibrant tile colors, no gradients, no text.
Icon-only, works at 32px and 512px. Material Design inspiration.
```

---

### Prompt 5 — 全景存档
```
App icon concept: an open archive drawer or filing cabinet seen from a slight isometric angle,
with multiple colorful document cards being pulled in from above by a magnetic force.
Each floating card represents a different content type (video, image, article, post).
The cabinet itself is sleek and minimal, dark slate color.
Accent colors on the cards: coral, sky blue, mint, amber.
Soft shadows, gentle depth, clean isometric illustration style.
No text, 1:1 ratio, suitable for an iOS or Android app store listing.
```

---

## 使用建议

| 工具 | 推荐提示词 | 风格设置 |
|------|-----------|---------|
| **Ideogram** | Prompt 1、4 | Style: Design，Aspect: 1:1 |
| **Midjourney** | Prompt 2、3 | `--ar 1:1 --style raw` |
| **DALL-E 3** | Prompt 5 | 直接使用 |
| **Recraft** | Prompt 1、4 | Vector illustration |

**通用 Negative Prompt（Ideogram 填入负向提示）：**
```python
text, letters, words, watermark, blurry, photo, realistic, 3D render, busy, cluttered
```

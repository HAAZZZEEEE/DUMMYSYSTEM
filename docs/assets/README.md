# 首页视觉资产

项目主视觉和 Workbench 截图随仓库提供。

| 文件 | 来源与用途 |
| --- | --- |
| `context-files.png` / `context-files-mobile.png` | 原创场景示意，展示虚构文件夹和实验产物散落在不同目录 |
| `context-chat-hd.png` / `context-chat-hd-mobile.png` | 原创场景示意，用方格代表旧对话并突出新会话里补交代的背景 |
| `hero.svg` / `hero-mobile.svg` | 本项目原创矢量主视觉，分别适配宽屏与窄屏 |
| `ptr-model.svg` / `ptr-model-mobile.svg` | Project / Task / Run 关系图，分别用于宽屏与窄屏 |
| `quote-open.svg` / `quote-close.svg` | 页尾引用装饰，引号使用独立 SVG 以兼容 GitHub |
| `dialogue-project*.svg` / `dialogue-task*.svg` / `dialogue-retrieve*.svg` | 三组自然语言工作流示意，宽屏与窄屏各一版；对话和指标均为合成示例，非实际运行回执 |
| `pilot-question.svg` | 页尾灰色小字反问，独立 SVG 保留 GitHub 上的颜色与字号 |
| `agent-governance.png` / `agent-governance-mobile.png` | 原创示意图，展示 AGENTS.md 的阅读及写入路由与 CLI 的校验 |
| `context-recovery.png` / `context-recovery-mobile.png` | 原创示意图，以合成的采样对比实验说明新会话如何从 Project、Task、Run 记录接续 |
| `file-map.svg` | 本项目原创文件归属图 |
| `workbench-project.png` | 作者当前工作区实拍：DUMMYSYSTEM 真实任务、Run 与进展文档，1600 × 1060 |
| `workbench-overview.png` | 作者当前工作区实拍：全局项目状态与存储空间，「专注」视图，1440 × 1200 |
| `workbench-homepage.png` | 独立演示工作区实拍：内嵌 `demo-project.html`，1440 × 960 |
| `demo-project.html` | 可复制的静态项目首页示例，HTML / CSS，无外部依赖 |

截图拍摄于 2026-11-16，Chromium 浏览器，macOS。两张真实工作区截图经作者明确选择用于公开首页，保留真实任务与空间统计；画面未包含密码或启动令牌。图片为实际页面捕获，未拼接或改画界面。浏览器截图不代表 Windows / macOS 原生窗口、同步或模型推理能力验收。

自定义首页图使用提交 `1e2fb2e` 的干净源码快照与独立初始化的工作区。演示 Project / Task / Run 通过 CLI 创建，状态按 create → start → finish 记录；Qwen Image 2.1 示例的文字与结果是合成资料，不构成真实模型评测。README 图片下方分别标明实拍与演示。

## 自定义首页示例

将 `demo-project.html` 复制到项目资源目录的 `homepage/index.html`，再按 [根 README 的「自定义项目首页」](../../README.md#自定义项目首页)配置 `workbench.json`。截图在浅色主题与绿色重点色下拍摄。

后续复拍优先使用作者授权的真实工作场景。检查正文、路径、机器档案与可见元数据，只将最终图片复制到本目录；环境、回执与原始执行证据留在源码之外。

## EVA 页尾配图

README 页尾的 `eva-unit-01.png`（初号机）和 `eva-dmysys-screen.png`（DMYSYS 标识）为作者提供的《新世纪福音战士》系列截图，第一张保留随截图提供的字幕。图片用于说明作品中的 DUMMY SYSTEM。版权归原作权利人所有，图片不参与软件打包，也不适用本仓库的 MIT 许可证。

## 首页配色

采用作者选定的「柔化经典」，以初号机紫绿配色为灵感，降低饱和度。仅作用于首页矢量视觉，实拍截图保留原始界面颜色。

- 主紫 `#78659D`：用户气泡、Project 节点及品牌元素。
- 柔绿 `#ADC67F`：标题强调及重点；浅绿 `#EAF0DF` 用于选中任务。
- 暖橙 `#C6966A`：预留少量点缀；失败状态文字使用较深的 `#8C5933` 保持可读性。
- 深底 `#2D2738`、浅底 `#F5F3F7`、Agent 回复浅绿 `#DDE8C9`：长文阅读与对话层次。

# 第三方资源与发布边界

浏览器资源随 Workbench wheel 分发，许可正文一起收入 workbench/static/vendor：

| 文件 | 上游 | 许可文件 |
|---|---|---|
| marked.js | [Marked 18.0.14](https://github.com/markedjs/marked/tree/v18.0.14) | marked-LICENSE.txt |
| purify.js | [DOMPurify 3.4.15](https://github.com/cure53/DOMPurify/tree/3.4.15) | purify-LICENSE.txt（Apache-2.0） |
| highlight.js | [highlight.js 11.12.0](https://github.com/highlightjs/highlight.js/tree/11.12.0) | highlight-LICENSE.txt（BSD-3-Clause） |

原版权头保留。highlight.js 取自上游 npm 的 @highlightjs/cdn-assets 11.12.0 发布包，下载后核对其 SHA-512 integrity；许可随包保留。原位图/ICO 来源未证实，已排除；候选 SVG 直接由几何图形编写。

Python 依赖由包管理器获取，其许可证留在相应 wheel 元数据中。项目自身许可证尚待作者决定。本文件不替代公开前的权利审查。


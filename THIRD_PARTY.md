# 第三方资源与发布边界

浏览器资源随 Workbench wheel 分发，许可正文一起收入 workbench/static/vendor：

| 文件 | 上游 | 许可文件 |
|---|---|---|
| marked.js | [Marked 18.0.14](https://github.com/markedjs/marked/tree/v18.0.14) | marked-LICENSE.txt |
| purify.js | [DOMPurify 3.4.15](https://github.com/cure53/DOMPurify/tree/3.4.15) | purify-LICENSE.txt（Apache-2.0） |
| highlight.js | [highlight.js 11.12.0](https://github.com/highlightjs/highlight.js/tree/11.12.0) | highlight-LICENSE.txt（BSD-3-Clause） |

原版权头保留。highlight.js 取自上游 npm 的 @highlightjs/cdn-assets 11.12.0 发布包，下载后核对其 SHA-512 integrity；许可随包保留。原位图/ICO 来源未证实，已排除；候选 SVG 直接由几何图形编写。

Python 依赖由包管理器获取，其许可证留在相应 wheel 元数据中。项目自有代码和随附方法论文档采用 [MIT 许可证](LICENSE.txt)，不改变第三方资源各自的许可证。各安装包中的 LICENSE.txt 是根许可证的同文副本，构建时必须核对一致。本文件不替代公开前的权利审查。


## README 页尾影像

README 收录两张作者提供的《新世纪福音战士》系列截图，来源与用途见 [首页资产说明](docs/assets/README.md#eva-页尾配图)。影像不进入安装包，不适用本仓库的 MIT 许可证，版权归原作权利人所有。

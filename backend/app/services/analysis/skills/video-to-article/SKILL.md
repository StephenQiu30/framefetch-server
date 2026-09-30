---
name: video-to-article
description: 把视频重组为适合微信公众号阅读和二次编辑的文章初稿，保留章节证据、核心观点与发布前事实说明。
license: MIT
metadata:
  video-server-display-name: 公众号文章
  video-server-default-prompt: 将视频重组为微信公众号文章初稿：确定读者问题与中心命题，采用移动端短段落和信息型小标题，并把时间证据集中留给编辑复核。
  video-server-order: "25"
  video-server-input-kinds: video
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: video-article
  video-server-references: references/wechat-editorial.md, shared/report-writing.md
---
# 视频整理为公众号文章

目标是一篇离开播放器也能顺畅阅读的公众号文章初稿，而不是逐句字幕、时间线摘要或视觉拉片表。文章先建立中心命题和读者问题，再按信息逻辑重组视频内容；服务端会把正文与编辑证据分开渲染，删掉编辑附录后正文仍应完整。

## 写作流程

1. 完整观察视频，列出可见的主题、案例、数字和画面文字、转折，以及证据的限制；连续长镜头里的不同信息阶段分开记录，不写成一条笼统的证据。
2. 选定一个中心命题和一种文章骨架，不把所有观察塞进同一篇文章。
3. 先形成章节论证链，再写标题、导语、正文、核心观点和结语。章节按问题推进，不按视频时间顺序复述。
4. 每章至少绑定一条真实的时间证据；证据留给编辑复核，不把时码写进正文。
5. 最后做事实、重复、移动端可读性、标题承诺和结尾新增结论的检查。

## 边界

- 没有可靠的字幕或音频时，不编造对白、演讲者身份、采访、引语或外部资料，把缺口写进 `limitations`。
- 字段中不放 Markdown、HTML、代码围栏或额外 JSON，排版由服务端完成。

文章骨架、字段写法、开头与结尾、移动端可读性和发布前检查见 `references/wechat-editorial.md`；通用文字要求见《报告写作规范》，两者冲突时以事实边界为准。

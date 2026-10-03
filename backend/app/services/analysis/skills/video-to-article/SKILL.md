---
name: video-to-article
description: 把视频重组为适合微信公众号阅读和二次编辑的文章初稿，保留章节证据、核心观点与发布前事实说明。
license: MIT
metadata:
  video-server-display-name: 公众号文章
  video-server-default-prompt: 写一篇编辑可以继续修改的公众号文章初稿，围绕视频证据能回答的一个读者问题展开。正文独立可读，时间证据放在编辑附录；素材不足时缩小命题，不补造背景、引语或效果。
  video-server-order: "25"
  video-server-input-kinds: video
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: video-article
  video-server-references: references/wechat-editorial.md, shared/report-writing.md
---
# 视频整理为公众号文章

目标是一篇离开播放器也能顺畅阅读的公众号文章初稿，而不是逐句字幕、时间线摘要或视觉拉片表。文章先建立中心命题和读者问题，再按信息逻辑重组视频内容；服务端会把正文与编辑证据分开渲染，删掉编辑附录后正文仍应完整。

## 写作流程

1. 从用户重点确定读者和文章用途，未提供时面向想了解片中具体过程的普通读者。完整观察视频，列出可见的主题、案例、数字和画面文字、转折，以及证据的限制；连续长镜头里的不同信息阶段分开记录。
2. 选定一个中心命题和一种文章骨架。先检查关键陈述是否有证据；视觉展示只能支持观察稿时就写观察稿，素材少时允许篇幅短、章节少，不把所有观察塞进文章或扩写成行业观点。
3. 先形成章节论证链，再写标题、导语、正文、核心观点和结语。章节按问题推进，不按视频时间顺序复述。
4. 每章至少绑定一条真实的时间证据；证据留给编辑复核，不把时码写进正文。
5. 最后按编辑审稿顺序检查：逐项核对事实与推断，删去正文和摘要的无效重复，再检查标题承诺、段落推进与结尾新增结论。不能靠增加口语、虚构亲历或“有人说”去除模板感。返回约定 JSON，不输出审稿过程。

## 边界

- 没有可靠的字幕或音频时，不编造对白、演讲者身份、采访、引语或外部资料，把缺口写进 `limitations`。
- 字段中不放 Markdown、HTML、代码围栏或额外 JSON，排版由服务端完成。

文章骨架、字段写法、开头与结尾、移动端可读性和发布前检查见 `references/wechat-editorial.md`；通用文字要求见《报告写作规范》，两者冲突时以事实边界为准。

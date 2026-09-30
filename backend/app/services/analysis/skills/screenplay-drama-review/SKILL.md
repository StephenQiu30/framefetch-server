---
name: screenplay-drama-review
description: 基于固定版本的 drama-skills 短剧审稿方法，检查故事承诺、人物选择、局部回报、连续记忆和重复机制。
license: MIT
metadata:
  video-server-display-name: 短剧故事审稿
  video-server-default-prompt: 重点审查故事承诺、每个段落的局部结果、人物选择与代价，以及重复情节是否真正改变意义。
  video-server-order: "61"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-analysis
  video-server-references: shared/report-writing.md, shared/screenplay-coverage-writing.md
  video-server-modules: drama-review-method, drama-story-script, drama-anti-template, humanizer-zh, zh-copywriting-guidelines
---

# 短剧故事审稿

直接使用下方固定来源的短剧审稿模块审阅本次上传的剧本。先检查场景覆盖与文本明确事实，再判断故事承诺、人物行动、局部结果和重复机制；每个问题说明可定位的文本表现、观众影响与需要恢复的结果。只把充分成立且影响大的问题放入 `priority_revisions`，没有依据时留空。

上游的文件、owner、状态、其他生产资料和跨文档工作流不在本次输入内；只审阅上传剧本，不推断不存在的素材。上游短剧分集量表在长片、单集或非传统结构上按实际文本条件使用，不要求固定钩子、节拍、页数或结尾形态。所有字段仍返回本项目的 `screenplay-analysis` JSON 契约，每个源场景恰好覆盖一次；内部 ID 不是证据。

## 成稿写法

报告面向要动手修改的作者：先读到该改什么，再读到依据。各字段在报告中的位置和写法见《剧本审稿报告写法》，通用文字规范见《报告写作规范》；上游写作模块只用于自查成稿表达，不改变审稿结论与输出契约。

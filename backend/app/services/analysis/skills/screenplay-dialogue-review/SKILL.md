---
name: screenplay-dialogue-review
description: 基于固定版本的 screenwriting-skills 对白模块，审阅说话目的、言语策略、人物声音和信息释放。
license: MIT
metadata:
  video-server-display-name: 剧本对白审阅
  video-server-default-prompt: 聚焦说话者的即时目的和策略、回应如何改变局面、人物声音是否可辨，以及对白是否重复已知事实。
  video-server-order: "64"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-analysis
  video-server-references: shared/report-writing.md, shared/screenplay-coverage-writing.md
  video-server-modules: sw-dialogue, drama-story-script, humanizer-zh, zh-copywriting-guidelines
---

# 剧本对白审阅

直接使用下方固定来源的对白模块，审阅台词作为行动所追求的结果、对方的回应、角色声音和信息释放。先指出具体交换中什么没有变化、为何影响理解或关系，再说明修订目标；不使用禁词表，不因沉默、方言或非写实表达而自动扣分。上游写台词与训练流程不在本任务执行。

按原文顺序覆盖全部源场景，对白特有发现放入 `dialogue_findings`，跨场重要缺口放入 `priority_revisions`；其他必填字段简洁且以文本为准。只返回项目 `screenplay-analysis` JSON，不生成未经请求的新台词。

## 成稿写法

报告面向要动手修改的作者：先读到该改什么，再读到依据。各字段在报告中的位置和写法见《剧本审稿报告写法》，通用文字规范见《报告写作规范》；上游写作模块只用于自查成稿表达，不改变审稿结论与输出契约。

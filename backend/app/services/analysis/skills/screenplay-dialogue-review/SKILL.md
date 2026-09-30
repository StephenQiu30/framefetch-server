---
name: screenplay-dialogue-review
description: 基于 screenwriting-skills 对白模块，审阅说话目的、言语策略、人物声音和信息释放。
license: MIT
metadata:
  video-server-display-name: 剧本对白审阅
  video-server-default-prompt: 聚焦说话者的即时目的和策略、回应如何改变局面、人物声音是否可辨，以及对白是否重复已知事实。
  video-server-order: "64"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-analysis
  video-server-modules: sw-dialogue, drama-story-script, humanizer-zh, zh-copywriting-guidelines
  video-server-references: shared/report-writing.md, shared/screenplay-coverage-writing.md
---

# 剧本对白审阅

用上文 sw-dialogue 的对白任务与瑕疵、解说处理、角色专属对白和节拍分析法，以及 drama-story-script 的对白问题，把台词当作行动来审阅：说话者此刻想从对方那里得到什么，用了什么策略，对方如何回应，局面有没有因此改变。

## 审阅重点

1. 具体的一组交换里，什么没有变化，为什么影响理解或关系。
2. 解说信息是通过冲突、证据或后果进入，还是中性的信息倾倒。
3. 人物的声音能否凭世界观、身份、关系、用词和节奏区分。

先指出具体的交换，再说明修订目标；不使用禁词表，不因沉默、方言或非写实表达自动扣分。上游的写台词训练不在本任务执行，也不生成未经请求的新台词。

## 输出分工

对白特有的发现放入 `dialogue_findings`，跨场的重要缺口放入 `priority_revisions`；其他必填字段简洁并以文本为准。字段写法见《剧本审稿报告写法》，通用文字要求见《报告写作规范》。只返回 `screenplay-analysis` JSON。

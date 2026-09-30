---
name: screenplay-character-review
description: 基于固定版本的 screenwriting-skills 人物与冲突模块，审阅目标、阻力、策略、选择和人物变化。
license: MIT
metadata:
  video-server-display-name: 剧本人物与冲突审阅
  video-server-default-prompt: 聚焦主要人物的目标、对手阻力、压力下的选择与可见后果，找出人物关系和弧线中影响故事的缺口。
  video-server-order: "62"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-analysis
  video-server-references: shared/report-writing.md, shared/screenplay-coverage-writing.md
  video-server-modules: sw-character-conflict, drama-story-script, humanizer-zh, zh-copywriting-guidelines
---

# 剧本人物与冲突审阅

直接使用下方固定来源的人物冲突模块，检查人物声称的价值与压力下采取的行动是否一致；说明目标、阻力、策略、选择、局部后果和可见变化。角色没有变化也可能是有效设计，不强迫成长；对手不必是更坏的人，安静的场景也不必制造对抗。上游创作练习与典型人物模板不作为本次剧本的验收条件。

按原文顺序覆盖每个源场景，其他必填字段保持简洁但真实。把跨场人物问题放入 `priority_revisions`，场景局部观察放入 `scenes[].findings`；没有充分依据时留空。只返回项目 `screenplay-analysis` JSON，内部源场景 ID 不代表引用证据。

## 成稿写法

报告面向要动手修改的作者：先读到该改什么，再读到依据。各字段在报告中的位置和写法见《剧本审稿报告写法》，通用文字规范见《报告写作规范》；上游写作模块只用于自查成稿表达，不改变审稿结论与输出契约。

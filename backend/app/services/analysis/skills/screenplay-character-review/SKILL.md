---
name: screenplay-character-review
description: 基于 screenwriting-skills 人物与冲突模块，审阅目标、阻力、策略、选择和人物变化。
license: MIT
metadata:
  video-server-display-name: 剧本人物与冲突审阅
  video-server-default-prompt: 聚焦主要人物的目标、对手阻力、压力下的选择与可见后果，找出人物关系和弧线中影响故事的缺口。
  video-server-order: "62"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-analysis
  video-server-modules: sw-character-conflict, drama-story-script, humanizer-zh, zh-copywriting-guidelines
  video-server-references: shared/report-writing.md, shared/screenplay-coverage-writing.md
---

# 剧本人物与冲突审阅

用上文 sw-character-conflict 的人物、主人公、对手、人物编排、冲突运动与弧光诊断，检查人物声称的价值与压力下的行动是否一致，写清目标、阻力、策略、选择、局部后果和可见的变化。

## 审阅重点

1. 主要人物各自想要什么，谁或什么在阻止，阻力是否与人物的弱点相关。
2. 压力升级时人物做了什么选择，选择带来什么后果，之后的策略有没有因此改变。
3. 人物编排是否形成对照：不同人物是否用不同的方式回应同一个核心冲突。

角色没有变化也可能是有效的设计，不强迫成长；对手不必是更坏的人，安静的场景也不必制造对抗。上游的角色小传、写作练习和人物模板不作为本次剧本的验收条件。

## 输出分工

`characters` 写主要人物的目标、阻力与变化；跨场的人物问题放入 `priority_revisions`，场景局部观察放入 `scenes[].findings`；没有充分依据时留空。其他必填字段简洁但真实。字段写法见《剧本审稿报告写法》，通用文字要求见《报告写作规范》。只返回 `screenplay-analysis` JSON。

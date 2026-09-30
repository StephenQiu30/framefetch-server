---
name: screenplay-scene-review
description: 基于固定版本的 screenwriting-skills 场景模块，审阅场景目标、节拍、状态变化和相邻场景衔接。
license: MIT
metadata:
  video-server-display-name: 剧本场景审阅
  video-server-default-prompt: 逐场审阅目标与阻力、行动和反应、场景进入及离开时的变化，并指出重复或无后果的节拍。
  video-server-order: "63"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-analysis
  video-server-references: shared/report-writing.md, shared/screenplay-coverage-writing.md
  video-server-modules: sw-scene-craft, drama-story-script, humanizer-zh, zh-copywriting-guidelines
---

# 剧本场景审阅

直接使用下方固定来源的场景设计模块，逐场识别其功能、行动、阻力、节拍和离场状态。场景可以用于余波、气氛、蒙太奇或转场；若它确实改变知识、关系、压力或节奏，不因缺少对抗和反转而判错。上游的删场、换址和写作练习只可转化为有文本依据的审稿问题，不直接修改原剧本。

按原文顺序覆盖全部源场景，局部问题写入 `scenes[].findings`，跨场重复或因果断裂写入 `priority_revisions`。只返回项目 `screenplay-analysis` JSON，不把内部源场景 ID 当成截图或事实依据。

## 成稿写法

报告面向要动手修改的作者：先读到该改什么，再读到依据。各字段在报告中的位置和写法见《剧本审稿报告写法》，通用文字规范见《报告写作规范》；上游写作模块只用于自查成稿表达，不改变审稿结论与输出契约。

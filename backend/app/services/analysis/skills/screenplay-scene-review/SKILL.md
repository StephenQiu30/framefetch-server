---
name: screenplay-scene-review
description: 基于 screenwriting-skills 场景模块，审阅场景目标、节拍、状态变化和相邻场景衔接。
license: MIT
metadata:
  video-server-display-name: 剧本场景审阅
  video-server-default-prompt: 逐场审阅目标与阻力、行动和反应、场景进入及离开时的变化，并指出重复或无后果的节拍。
  video-server-order: "63"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-analysis
  video-server-modules: sw-scene-craft, drama-story-script, humanizer-zh, zh-copywriting-guidelines
  video-server-references: shared/report-writing.md, shared/screenplay-coverage-writing.md
---

# 剧本场景审阅

用上文 sw-scene-craft 的场景设计、进出与节奏、动作优于对白、悬念与细节诊断，以及 drama-story-script 的场景测试，逐场识别功能、行动、阻力、节拍和离场状态。

## 审阅重点

1. 这一场为什么必须存在，谁的议程在组织它，什么力量在反对。
2. 进场与离场时，人物的处境、信息、关系或压力发生了什么变化。
3. 节拍是否推进：动作与反应是否改变局面，还是在重复同一个回合。
4. 相邻场景之间的衔接：离场状态是否给下一场施加压力。

余波、气氛、蒙太奇和转场类的场景，只要确实改变了知识、关系、压力或节奏，就不因缺少对抗和反转而判错。上游的删场、换址和写作练习只能转化为有文本依据的审稿问题，不直接修改原剧本。

## 输出分工

局部问题写入 `scenes[].findings`，跨场的重复或因果断裂写入 `priority_revisions`。字段写法见《剧本审稿报告写法》，通用文字要求见《报告写作规范》。只返回 `screenplay-analysis` JSON。

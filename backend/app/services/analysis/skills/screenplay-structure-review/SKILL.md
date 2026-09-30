---
name: screenplay-structure-review
description: 审阅剧本节拍、场景推进、转折、连续性和整体节奏。用于诊断场景单独成立但全局推进不足的中文或英文剧本。
license: MIT
metadata:
  video-server-display-name: 剧本结构审阅
  video-server-default-prompt: 聚焦节拍、场景推进、关键转折、连续性和节奏，给出按影响排序的结构修改建议。
  video-server-order: "70"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-analysis
  video-server-modules: sw-story-structure, sw-scene-craft, sw-premise-theme, sw-truby-anatomy, humanizer-zh, zh-copywriting-guidelines
  video-server-references: references/structure-rules.md, shared/report-writing.md, shared/screenplay-coverage-writing.md
---

# 剧本结构审阅

把每个源场景看作因果链中的一环，审阅目标、阻力、结果、反应与下一步选择如何累积成全局结构。判断要能回到已上传原文的具体位置，但内部源场景 ID 只用于覆盖校验，不能充当证据。

## 上游方法的用法

- sw-story-structure 与 sw-scene-craft：结构层级、激励事件与进展纠葛、危机高潮结局、场景设计与进出节奏，用来定位推进在哪里停滞。
- sw-premise-theme：先检查前提、主控思想与“渴望 vs 错误信念”是否在文本中成立，再判断结构是否服务于它。
- sw-truby-anatomy：用七大关键步骤、中段五个组件和中段松散十问，定位“每场都成立但连不起来”的原因。

这些方法是诊断视角，不要求剧本套用固定步骤数、页码、分钟数或三幕比例；“每场必须转折”这类写作建议也不是本任务的硬标准。

## 工作规则

1. 识别实际的节拍和压力变化，不把场景标题或固定页数当作节拍。
2. 检查每场是否改变人物的处境、信息、关系或选择，并说明它与前后场的因果连接。
3. 判断关键转折是否真正收窄或改变了后续的选项，铺垫与兑现是否闭合。
4. 检查时间、地点、人物知识、道具、关系状态和行动后果的连续性。
5. 区分必要的情绪消化与重复停滞，指出过快、过慢或强度单调的具体区段。
6. 源场景是文本因果单位，不是未来的镜头清单；不按篇幅、段落或预设覆盖率估算镜头数量。

结构问题放入 `priority_revisions`，非结构字段保持简洁但完整，不补造文本事实。检查清单见 `references/structure-rules.md`，字段写法见《剧本审稿报告写法》，通用文字要求见《报告写作规范》。只返回 `screenplay-analysis` JSON。

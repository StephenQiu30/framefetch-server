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
  video-server-modules: sw-story-structure, sw-scene-craft, screenwriting-skills-sw-premise-theme-skill, screenwriting-skills-sw-truby-anatomy-skill
  video-server-references: references/structure-rules.md
---

# 剧本结构审阅

把每个源场景视为因果链中的一环，审阅目标、阻力、结果、反应与下一步选择如何累积成全局结构。直接加载上游 `sw-story-structure` 和 `sw-scene-craft` 的指定审阅章节；其中固定页码、场景数量、三幕形状及“每场必须转折”等写作建议不是本任务的硬性质量标准。场景相关判断须能回到已上传原文的位置，但内部源场景 ID 只用于覆盖校验，不能充当证据。不直接创建资产、镜头或人工决策。

## 引用方法的用法（前提、主题与 Truby 结构）

上文新增的前提与主题（埃格里、麦基、克龙、希克斯、陆军）和 Truby 结构方法只作为诊断视角：先检查前提、主控思想与“渴望 vs 错误信念”是否在文本中成立，再用 Truby 的关键步骤、中段组件与场景编排定位结构松散处。不得要求剧本套用固定步骤数或页码，所有结论必须引用真实源场景。

## 工作规则

1. 识别实际节拍和压力变化，不把场景标题或固定页数当作节拍。
2. 检查每场是否改变人物处境、信息、关系或选择，并说明与前后场的因果连接。
3. 判断关键转折是否真正收窄或改变后续选项，检查铺垫与兑现是否闭合。
4. 检查时间、地点、人物知识、道具、关系状态和行动后果的连续性。
5. 区分必要的情绪消化与重复停滞，指出过快、过慢或强度单调的具体区段。
6. 把场景中的角色、地点、道具和可视化动作当作可供后续生产确认的事实线索，不把它们写成已经确认的资产或镜头。
7. 对对白覆盖、场景推进、连续性和可能遗漏分别说明文本事实与分析判断；必要时把问题放入 `priority_revisions`，不要新增当前契约没有的字段。
8. 使用 `screenplay-analysis` 结果契约表达结构重点；非结构字段保持简洁但完整，不补造文本事实。
9. 源场景是文本因果单位，不是未来镜头清单；不得按篇幅、段落或预设覆盖率估算镜头数量。镜头化建议只能说明需要保留的动作、空间、状态和对白事实。

详细检查清单见 [structure-rules](references/structure-rules.md)。

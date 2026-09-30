---
name: highlights
description: 用统一量表筛选视觉冲击、信息转折、情绪变化和可剪辑性兼具的片段。用于高光、预告和传播素材候选提炼。
license: MIT
metadata:
  video-server-display-name: 高光提炼
  video-server-default-prompt: 完整观察全片，按视觉显著性、信息或情绪转折、上下文独立性、可剪辑性和连续性风险筛选少量、互有差异的高光候选。
  video-server-order: "40"
  video-server-input-kinds: video
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: video-visual-analysis
  video-server-references: references/highlight-rubric.md, shared/report-writing.md
---
# 高光提炼

先保证全片分镜结构正确，再筛选少量、互有差异、可复核的高光候选。高光可以是单个分镜，也可以是完成同一节拍的连续几个分镜。所有结果都是待比较的候选，不是已经确认的主选，也不是平台效果结论。

## 选择原则

1. 对所有候选使用同一量表，优先保留在视觉显著性、信息或情绪转折、上下文独立性、可剪辑性上有明确优势的片段。
2. 高光范围包含完整的可见动作或转折，不从动作中间开始，也不在结果出现前结束。
3. 先用 `scenes` 还原候选所在的完整段落，再判断可以独立裁切的范围，不把建立信息和结果反应丢在候选之外。
4. 同质候选只保留证据最完整、构图最清晰或转折最充分的一项。
5. 没有成立的候选时返回空数组，报告会如实说明，不为凑数降低标准。

## 成稿重点

- `highlights[].title` 写出片段里发生了什么，例如“杯子落地前的定格”，不写“高光一”“精彩瞬间”。
- `summary` 概括全片高光的分布和最强候选，不重复每个候选的描述。
- `production_advice` 可以提出预告、复刻或封面候选的下一步验证，但不声称已经发布或选定。

量表、分值换算、边界、去重和字段写法见 `references/highlight-rubric.md`，通用文字要求见《报告写作规范》。

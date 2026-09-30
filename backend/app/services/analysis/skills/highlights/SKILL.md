---
name: highlights
description: 用统一量表筛选视觉冲击、信息转折、情绪变化和可剪辑性兼具的片段。用于高光、预告和传播素材候选提炼。
license: MIT
metadata:
  video-server-display-name: 高光提炼
  video-server-default-prompt: 完整观察并区分真实编辑边界与连续视觉节拍后，按视觉显著性、信息或情绪转折、上下文独立性、可剪辑性和连续性风险筛选高光。
  video-server-order: "40"
  video-server-input-kinds: video
  video-server-output-contract: video-visual-analysis
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-references: references/highlight-rubric.md, shared/report-writing.md
---
# 高光提炼

先保证全片分析分镜结构正确，再筛选少量、互有差异且可复核的高光候选。分析分镜既包括物理编辑，也包括连续长镜头内有明确进入、变化和退出状态的视觉节拍；高光可以是单项或完成同一节拍的连续组合。

## 选择原则

1. 对所有候选使用同一量表，优先保留在视觉显著性、信息/情绪转折、上下文独立性或可剪辑性上有明确优势的片段。
2. 高光范围应包含完整的可见动作或转折，避免从动作中间开始、在结果出现前结束。
3. 先用 `scenes` 恢复候选所处的完整场景任务，再判断可独立裁切范围；不要把建立信息和结果反应误丢在候选之外。
4. 同质候选只保留证据最完整、构图最清晰或转折最充分的一项，并在理由中说明其差异。
5. `evidence_shot_ids` 必须位于候选范围内；`score` 是本次视频内的相对评分，不代表播放量、转化或受众偏好。
6. `production_advice` 可提出预告/复刻/封面候选的下一步验证，但不得声称已经发布或选定。
7. 连续阶段边界使用 `transition_in=continuous`，边界成立但转场类型不明时使用 `unknown`；不得因没有 Cut 就让整片成为一个高光范围，也不得按固定秒数制造候选。

所有高光结果都是待比较候选，不是用户已经确认的主选或平台效果结论。

## 成稿写法

高光在报告中按“标题 → 描述 → 为什么值得保留 → 回看片段与相对分值”排版。文字规范见《报告写作规范》，这里只补充本 Skill 的重点。

- `highlights[].title` 写出该片段发生了什么，例如“杯子落地前的定格”，不写“高光一”或“精彩瞬间”。
- `description` 用 2–3 句写清片段的起点、变化和结果；`reason` 说明它在量表上的优势以及与相似候选的差别。
- `summary` 概括全片高光的分布和最强候选，不重复每个候选的描述。
- 没有成立的候选时返回空数组，报告会如实说明，不为凑数降低标准。

量表、去重规则和完整性检查见 `references/highlight-rubric.md`。最终只返回 `video-visual-analysis` Schema。

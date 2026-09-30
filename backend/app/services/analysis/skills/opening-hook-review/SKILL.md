---
name: opening-hook-review
description: 审查视频开场前 3、5 和 15 秒的可见注意力锚点、内容承诺、画面文字、视觉进展与正文衔接。用于短视频、口播和产品片的开场优化。
license: MIT
metadata:
  video-server-display-name: 开场钩子审查
  video-server-default-prompt: 完整观察全片并区分真实编辑边界与连续视觉节拍，重点审查开场 3、5、15 秒的主体锚点、内容承诺、文字可读性、画面进展和正文衔接。
  video-server-order: "45"
  video-server-input-kinds: video
  video-server-output-contract: video-visual-analysis
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-references: references/opening-hook-rubric.md, shared/report-writing.md
---
# 开场钩子审查

目标是用可复核的画面证据回答：观众最先看到什么、开场承诺了什么、画面如何持续推进，以及这个承诺是否在后续画面中兑现。它不预测平台留存率，也不用主观的“吸引人”代替具体观察。

## 执行流程

1. 先覆盖完整时间轴并建立同时包含真实编辑边界与连续视觉节拍的 `shots` 和连续 `scenes`；不得因聚焦开场而省略后续内容，也不得因开场是长镜头就把所有进展压成一镜。
2. 分别审查 0–3 秒的注意力锚点、0–5 秒的可见内容承诺和 0–15 秒的视觉进展；视频更短时截断到权威时长。
3. 检查主体、动作、构图、画面文字、状态变化、镜头变化和进入正文的衔接。区分有目的进展、无变化停滞、无意义快切与信息过载。
4. 用后续分镜检查开场的视觉承诺是否兑现；不把想象中的台词、音效或发布表现当作证据。
5. 把结论写成“可见观察 → 对理解或节奏的影响 → 必须达到的修订结果”，并引用真实 `shot.id`。

## 输出纪律

- `summary` 概括开场最强证据、最大风险和后续兑现情况，不编造总分或平台指标。
- 开场分镜的 `visual_tags` 使用量表中的受控前缀；`description` 和 `narrative_function` 仍保留可见事实、起止状态与镜头任务。
- `highlights` 只保留少量真正支持开场判断的候选；没有成立候选时返回空数组，不为满足数量而虚构优势。
- `production_advice` 按影响和可执行性排序，明确哪些分镜应保留、前移、简化、放大、重组或进一步人工复核。
- 高光分数只用于本结果内候选的相对比较，不表示停留、完播、点击、转化或审美概率。

## 边界

当前运行时没有可靠音频证据时，不评价开场台词、语速、音乐卡点、音效、口型或情绪语气。画面不足以支持判断时保留不确定性；审查结果是创作建议，不是自动剪辑、发布或市场效果承诺。

连续镜头内新的锚点、承诺、发展或正文交接形成独立阶段时使用 `transition_in=continuous`；边界成立但类型不明时使用 `unknown`。3/5/15 秒是审查窗口，不是固定秒数的机械分镜切点。

## 成稿写法

报告的读者最关心开场该保留什么、改什么。文字规范见《报告写作规范》，这里只补充本 Skill 的重点。

- `title` 写出开场最关键的判断，例如“前三秒有动作，但承诺到第十二秒才出现”。
- `summary` 依次写：开场最强的证据、最大的风险、后续是否兑现开场承诺。
- 开场所在的 `scenes[].description` 按 0–3 秒、0–5 秒、0–15 秒三个窗口顺序写成一段，窗口之间用承接句连起来，不写成清单。
- `production_advice.recommended_extensions` 每条写清要保留、前移、简化、放大或重组的分镜，以及修改后开场应达到的效果。

评估维度、标签、特殊情况和交付自检见 `references/opening-hook-rubric.md`。最终只返回 `video-visual-analysis` Schema。

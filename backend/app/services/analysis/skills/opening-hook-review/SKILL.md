---
name: opening-hook-review
description: 审查视频开场前 3、5 和 15 秒的可见注意力锚点、内容承诺、画面文字、视觉进展与正文衔接。用于短视频、口播和产品片的开场优化。
license: MIT
metadata:
  video-server-display-name: 开场钩子审查
  video-server-default-prompt: 完整观察全片，重点审查开场 3、5、15 秒的主体锚点、内容承诺、文字可读性、画面进展和正文衔接，并检查承诺是否兑现。
  video-server-order: "45"
  video-server-input-kinds: video
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: video-visual-analysis
  video-server-references: references/opening-hook-rubric.md, shared/report-writing.md
---
# 开场钩子审查

目标是用可复核的画面证据回答：观众最先看到什么、开场承诺了什么、画面如何持续推进，以及这个承诺是否在后续画面中兑现。读者最关心开场该保留什么、改什么。本审查不预测平台留存率，也不用主观的“吸引人”代替具体观察。

## 执行流程

1. 先覆盖完整时间轴并建立分镜与段落；不因聚焦开场而省略后续内容，也不因开场是长镜头就把所有进展压成一镜。
2. 分别审查 0–3 秒的注意力锚点、0–5 秒的内容承诺和 0–15 秒的视觉进展；视频更短时截断到实际时长。3/5/15 秒是审查窗口，不是分镜切点。
3. 检查主体、动作、构图、画面文字、状态变化和进入正文的衔接，区分有目的的进展、停滞、碎片化与信息过载。
4. 用后续分镜检查开场承诺是否兑现。
5. 把结论写成“可见观察 → 对理解或节奏的影响 → 修订后要达到的效果”。

## 边界

没有可靠音频证据时，不评价开场台词、语速、音乐卡点、音效、口型或语气。高光分数只用于本结果内候选的相对比较，不表示停留、完播、点击、转化或审美概率。审查结果是创作建议，不是自动剪辑、发布或市场效果承诺。

## 成稿重点

- `title` 写出开场最关键的判断，例如“前三秒有动作，但承诺到第十二秒才出现”。
- `summary` 依次写：开场最强的证据、最大的风险、后续是否兑现开场承诺。
- 开场所在段落的 `description` 按 0–3 秒、0–5 秒、0–15 秒三个窗口顺序写成连贯的一段，窗口之间用承接句连接，不写成清单。
- `highlights` 只保留真正支持开场判断的候选，没有就返回空数组。

评估维度、标签、字段写法和自检见 `references/opening-hook-rubric.md`，通用文字要求见《报告写作规范》。

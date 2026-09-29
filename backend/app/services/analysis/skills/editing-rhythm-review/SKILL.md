---
name: editing-rhythm-review
description: 审阅成片的物理剪辑与连续镜头内部节奏、停留、信息密度、边界动机和动作衔接。用于发现拖沓、无目的快切、信息过载与节奏断裂。
license: MIT
metadata:
  video-server-display-name: 剪辑节奏审阅
  video-server-default-prompt: 完整观察时间线，区分真实编辑切点与连续视觉节拍，审阅停留、信息密度、边界动机、动作和构图衔接，区分必要停留、拖沓、无目的快切和信息过载。
  video-server-order: "42"
  video-server-input-kinds: video
  video-server-modules: drama-skills-short-drama-edit-cut-craft, marketingskills-video-edit-anatomy
  video-server-output-contract: video-visual-analysis
  video-server-references: references/editing-rhythm-rubric.md
---
# 剪辑节奏审阅

目标不是追求更多 Cut 或统一镜头时长，而是判断每次停留和切换是否给观看者足够时间读懂画面，并让动作、信息和段落目标持续推进。

## 引用方法的用法

上文的 Source module 是固定版本的上游方法，原本写给分镜与剪辑制作流程。这里只把其中的判断标准用于审阅已经完成的视频：
- 只评价画面中可见的决策，不输出分镜稿、剪辑单、关键帧或生成提示词，也不涉及其中提到的项目文件、字段、工具或下游环节。
- 当前没有可靠音频证据：凡是依赖台词发声、音乐、音效或声音桥的条目一律不评价，必要时在局限中说明。
- 上游示例与数字（如镜长、景别阶梯）是参考而非配额；结论必须回到本片的真实分镜证据。
- 剪辑解剖（edit anatomy）的逐拍维度用于识别本片的切点节奏、画面文字、运动与标志性手法；其中的“复刻参考剪辑”目标不适用，不建议照搬他人成片。

## 工作方法

1. 完整覆盖真实编辑边界与连续视觉节拍组成的时间线，比较每个分析分镜的信息量、主体动作、构图变化与停留时长；不得把连续长镜头的多个任务阶段合成一个平均值。
2. 判断切点是否由动作完成、视线/主体变化、信息揭示、空间转换或段落转折支持。
3. 区分有目的停留、无变化拖延、重复信息、无目的快切和同一时刻的信息过载；镜头长短本身不直接代表好坏。
4. 纵向检查段落节奏是否形成可辨认的建立、加速、释放或收束，而不是只统计平均镜头时长。
5. 把修订建议落实到真实分镜与可验证结果，例如缩短重复停留、延长关键信息阅读、调整切点或减少同时竞争的视觉元素。

## 输出边界

- `summary` 概括全片节奏形态、最清晰的有效段落与首要节奏风险。
- 分镜 `narrative_function` 说明停留或切换的用途；`visual_tags` 使用参考量表中的节奏与切点前缀。
- `production_advice` 必须给出分镜证据和期望结果，不给出脱离素材的固定秒数公式。
- 当前没有可靠音频证据时，不评价音乐卡点、语速、停顿、音效或声音桥。
- 真实 Cut/转场按类型记录；无编辑但节拍已经重置时使用 `transition_in=continuous`，边界类型不明时使用 `unknown`。连续节拍不计作物理剪辑频率，也不得按固定秒数切片。

具体量表、标签和特殊情况见 `references/editing-rhythm-rubric.md`。最终只返回 `video-visual-analysis` Schema。

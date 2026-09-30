---
name: scene-extraction
description: 把编辑镜头与连续视觉节拍归并为可复核的场景段落，提炼空间、主体事件、叙事任务、视觉规则和连续性风险。用于场景拆解与复用准备。
license: MIT
metadata:
  video-server-display-name: 场景提炼
  video-server-default-prompt: 在完整分析分镜时间线上提炼场景段落，区分真实编辑边界与连续长镜头节拍，逐场说明空间、事件、视觉规则、进出场依据和连续性风险。
  video-server-order: "35"
  video-server-input-kinds: video
  video-server-output-contract: video-visual-analysis
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-references: references/scene-boundaries.md, shared/report-writing.md
---
# 场景提炼

目标是把逐镜头时间线提升为可用于剧本回溯、场景资产整理和后续制作的场景段落。场景不是单个 Cut、固定时长分段或地点资产的别名，而是一组在稳定时空和连续事件中共同完成同一主要任务的相邻镜头。

## 执行原则

1. 先完成包含真实编辑边界与连续视觉节拍的 `shots`，再自下而上归并 `scenes`；不得先猜场景再强迫分镜服从，也不得因整段没有 Cut 就省略内部阶段。
2. 场景边界必须有至少一种可见依据：空间切换、时间状态重置、主体/事件目标改变、视觉规则明显重置或段落进出场完成。
3. 每个镜头必须且只能属于一个场景；场景按时间顺序连续覆盖全部镜头，不允许跨越无关镜头合并同一地点。
4. 同一地点不一定是同一场景；交叉剪辑回到同一地点时，应按连续时间段建立新场景并在描述中说明呼应关系。
5. `location` 只写可见空间身份；无法确认真实地名、时间或人物关系时使用保守描述。
6. 场景边界发生在连续长镜头内部时，先以 `transition_in=continuous` 建立对应分析分镜，再据此分场；边界类型不明用 `unknown`，禁止固定时长切片。

## 交付重点

- `description` 概括场景中的主体、事件推进、开始状态和结束状态。
- `narrative_function` 说明该场景在全片中的主要任务及进入/退出依据。
- `visual_rules` 提炼场景内稳定可复用的构图、光色、机位、运动和关键资产约束。
- `continuity_risks` 只记录具体可检查的问题；没有明确风险时返回空数组。
- 场景、高光和资产都是候选信息，不代表已创建项目场景或完成主选。

## 成稿写法

场景段落在报告中按“标题 → 时间与空间 → 段落描述 → 这一段在做什么 → 视觉规则 → 风险”排版，连起来读应当是一份场景大纲。文字规范见《报告写作规范》，这里只补充本 Skill 的重点。

- `scenes[].title` 写成该场完成的事，例如“店员把样品递到镜头前”，不写“场景一”或地点名。
- `description` 写成 2–4 句的小段落：开始状态、事件推进、结束状态。
- `narrative_function` 一句话交代该场在全片中的任务和进出场依据；`visual_rules` 每条是一条可复用的约束；`continuity_risks` 每条写清具体位置和影响。
- `summary` 概括全片的场景划分方式和最关键的一次场景转换。

边界判定、字段写法和验收规则见 `references/scene-boundaries.md`。最终只返回 `video-visual-analysis` Schema。

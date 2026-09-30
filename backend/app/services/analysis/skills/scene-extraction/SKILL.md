---
name: scene-extraction
description: 把编辑镜头与连续视觉节拍归并为可复核的场景段落，提炼空间、主体事件、叙事任务、视觉规则和连续性风险。用于场景拆解与复用准备。
license: MIT
metadata:
  video-server-display-name: 场景提炼
  video-server-default-prompt: 在完整的分析分镜时间线上提炼场景段落，逐场说明空间、事件、视觉规则、进出场依据和连续性风险。
  video-server-order: "35"
  video-server-input-kinds: video
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: video-visual-analysis
  video-server-references: references/scene-boundaries.md, shared/report-writing.md
---
# 场景提炼

目标是把逐镜头时间线提升为可用于剧本回溯、场景资产整理和后续制作的场景大纲。场景不是单个 Cut、固定时长分段或地点资产的别名，而是一组在稳定时空和连续事件中共同完成同一主要任务的相邻镜头。报告按“标题 → 时间与空间 → 段落描述 → 段落作用 → 视觉规则 → 连续性风险”逐场排版，连起来读应当是一份场景大纲。

## 执行原则

1. 先完成分析分镜时间线，再自下而上归并 `scenes`；不先猜场景再让分镜服从。
2. 场景边界必须至少有一种可见依据：空间切换、时间状态重置、主体或事件目标改变、视觉规则明显重置、段落进出场完成。
3. 每个镜头只属于一个场景；场景按时间顺序连续覆盖全部镜头，不跨越无关镜头合并同一地点。
4. 同一地点不一定是同一场景；交叉剪辑回到同一地点时，按连续时间段建立新场景，并在描述中说明呼应关系。
5. `location` 只写可见空间；无法确认真实地名、时间或人物关系时使用保守描述。

## 成稿重点

- `title` 写成该场完成的事，例如“店员把样品递到镜头前”，不写“场景一”或地点名。
- `summary` 概括全片的场景划分方式和最关键的一次场景转换。

边界判定、字段写法和验收规则见 `references/scene-boundaries.md`，通用文字要求见《报告写作规范》。

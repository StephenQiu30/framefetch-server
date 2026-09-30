---
name: director-breakdown
description: 逐分镜复盘成片的调度、构图、镜头动机与剪辑关系，并转成可执行的复刻或修改建议。用于完整视频的专业导演拉片。
license: MIT
metadata:
  video-server-display-name: 导演拉片
  video-server-default-prompt: 逐分镜拉片，复盘调度、构图、镜头动机、剪辑关系和连续性，说明每个关键决策为什么成立，并给出可执行的复刻或修改建议。
  video-server-order: "10"
  video-server-input-kinds: video
  video-server-modules: drama-shot-craft, drama-shot-grammar, drama-blocking-playbooks, humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: video-visual-analysis
  video-server-references: references/director-method.md, shared/report-writing.md
---
# 导演拉片

交付物是一份导演拉片笔记：解释每个分析分镜为什么成立、画面如何组织注意力、相邻分镜如何共同完成一个节拍，以及这些观察怎样转成复刻或修改时可以照做的约束。读者是导演、摄影和剪辑，他们要的是判断和依据，不是景别清单。

## 上游方法的用法

上文的 drama-shot-craft、drama-shot-grammar 和 drama-blocking-playbooks 原本写给分镜制作，这里把其中的判断问题用于复盘已完成的成片：镜头目的是否成立、调度是否表达人物策略、轴线与屏幕方向是否一致、切点是否带来可见变化、证据是否被读到。

- 只评价画面中可见的决策。上游提到的分镜文档、字段编号（如 `SHT-02`）、资产、关键帧和提示词环节不属于本任务，不在结果中出现。
- 上游的景别阶梯和示例是判断参照，不是配额；结论必须回到本片的分镜证据。
- 没有可靠音频证据时，依赖台词、音乐、声音桥的判断不做，必要时在摘要中说明。

## 执行顺序

1. 先完整覆盖全片，再复核疑似边界。低对比转场、遮挡转场和连续长镜头内的任务变化都要语义复核。
2. 对每个分镜依次看边界、调度、摄影与美术、剪辑关系和叙事节拍，禁止用风格形容词替代观察。
3. 纵向检查镜头序列，把连续完成同一任务的相邻镜头归入 `scenes`：空间如何建立、视线与运动方向是否连贯、景别变化服务什么、节奏在哪里转折。
4. 最后评高光、资产和复刻优先级。

## 成稿重点

- `title` 写出这支片子在调度上的核心特点或问题，例如“固定机位撑起全片，信息靠人物走位递进”，不写“导演拉片报告”。
- `summary` 依次交代：画面靠什么组织注意力、最成立的一处导演决策、最值得复查的一处风险，并点到具体分镜。
- 每个 `scenes[].description` 写成 2–4 句的小段落，说明这组镜头在空间、调度和节拍上如何配合。
- `production_advice` 先用一段话说明优先顺序，再逐条给出可以照做的复刻或修改约束。

分镜字段写法、标签词表、分值口径和交付自检见 `references/director-method.md`，通用文字要求见《报告写作规范》。

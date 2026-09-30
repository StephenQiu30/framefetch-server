---
name: editing-rhythm-review
description: 审阅成片的物理剪辑与连续镜头内部节奏、停留、信息密度、切点动机和动作衔接。用于发现拖沓、无目的快切、信息过载与节奏断裂。
license: MIT
metadata:
  video-server-display-name: 剪辑节奏审阅
  video-server-default-prompt: 完整观察时间线，审阅停留、信息密度、切点动机、动作和构图衔接，区分必要停留、拖沓、无目的快切和信息过载。
  video-server-order: "42"
  video-server-input-kinds: video
  video-server-modules: drama-edit-cut-craft, humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: video-visual-analysis
  video-server-references: references/editing-rhythm-rubric.md, shared/report-writing.md
---
# 剪辑节奏审阅

目标不是追求更多 Cut 或统一镜头时长，而是判断每次停留和切换是否给观看者足够时间读懂画面，并让动作、信息和段落目标持续推进。读者要看到具体的停留与切换，而不是“节奏偏慢”这样的笼统结论。

## 上游方法的用法

上文 drama-edit-cut-craft 的“镜序与相邻关系”用于判断相邻镜头的切换是否暴露跳动、重复信息是否有新增作用。它原本写给剪辑制作，这里只用来审阅已完成的成片，不输出剪辑单。

## 工作方法

1. 完整覆盖时间线，比较每个分析分镜的信息量、主体动作、构图变化与停留时长；连续长镜头按任务阶段分别判断，不合成一个平均值。
2. 判断每个切点是否由动作完成、视线或主体变化、信息揭示、空间转换或段落转折支持。
3. 区分有目的的停留、无变化的拖延、重复信息、无目的快切和同一时刻的信息过载；镜头长短本身不代表好坏。
4. 纵向检查段落节奏是否形成可辨认的建立、加速、释放或收束，而不是只统计平均镜长。
5. 把修改建议落到具体分镜和可验证的结果上，例如缩短重复停留、延长关键信息的阅读时间、调整切点、减少同时竞争的视觉元素。

## 边界

- 没有可靠音频证据时，不评价音乐卡点、语速、停顿、音效或声音桥。
- 连续节拍不计入物理剪辑频率；物理剪辑频率与镜头内部节拍分开描述。
- 不给脱离素材的固定秒数公式或行业阈值。

## 成稿重点

- `title` 写出节奏上的核心判断，例如“中段三次重复停留拖慢了演示”。
- `summary` 依次写：全片节奏形态、最清晰的有效段落、首要节奏风险。
- 段落 `description` 说明这一段的节奏如何建立、加速或收束，并点到具体分镜。

量表、标签、判断规则和字段写法见 `references/editing-rhythm-rubric.md`，通用文字要求见《报告写作规范》。

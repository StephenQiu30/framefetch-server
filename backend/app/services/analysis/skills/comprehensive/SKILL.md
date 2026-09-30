---
name: comprehensive
description: 以证据链方式整合镜头结构、内容段落、节奏、高光、资产与制作策略。用于需要完整决策概览的视频分析。
license: MIT
metadata:
  video-server-display-name: 综合分析
  video-server-default-prompt: 完整覆盖视频，建立“分镜事实—段落结构—高光与资产—制作策略”证据链，指出关键转折、连续性风险和优先行动。
  video-server-order: "20"
  video-server-input-kinds: video
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: video-visual-analysis
  video-server-references: references/evidence-synthesis.md, shared/report-writing.md
---
# 综合视频分析

综合分析不是把其他模式各写一小段，而是把镜头事实组织成一条可复核的证据链：先回答画面发生了什么，再回答结构如何变化，最后给出候选价值和下一步制作策略。读者往往只有几分钟，导语和段落标题就要交代完主线。

## 执行流程

1. 完整覆盖全片，建立分析分镜时间线。
2. 按视觉目标、空间、主体和节奏变化识别内容段落，写入 `scenes`；每个段落共同完成一个主要任务。
3. 从具体镜头归纳摘要、转折和视觉模式。
4. 分别建立高光候选与资产候选，再检查它们是否覆盖核心段落，不按数量平均分配。
5. 制作建议按影响、可执行性和连续性风险排序，写明优先分镜和验收条件。

## 工作边界

- 区分观察、解释、建议三种陈述：解释不得冒充事实，建议不得冒充已经执行的决策。
- 摘要覆盖全片结构，不只复述最醒目的开头或结尾。
- 无法由画面确认的对白、人物身份、因果、外部背景和传播结果不补齐。

## 成稿重点

- `title` 写出全片最核心的判断，例如“前半段靠产品特写建立信任，后半段节奏松散”。
- `summary` 按“这是什么内容 → 结构主线 → 最强之处 → 首要风险”写 2–4 句，每个判断点到分镜或段落。
- 各段落的 `title` 写成该段完成的事，连起来读就是全片提纲。

证据层级、字段写法、覆盖矩阵和建议优先级见 `references/evidence-synthesis.md`，通用文字要求见《报告写作规范》。

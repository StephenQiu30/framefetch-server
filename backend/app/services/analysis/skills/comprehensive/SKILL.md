---
name: comprehensive
description: 以证据链方式整合镜头结构、内容段落、节奏、高光、资产与制作策略。用于需要完整决策概览的视频分析。
license: MIT
metadata:
  video-server-display-name: 综合分析
  video-server-default-prompt: 完整覆盖视频并区分真实编辑边界与连续视觉节拍，建立“分镜事实—段落结构—高光与资产—制作策略”证据链，指出关键转折、连续性风险和优先行动。
  video-server-order: "20"
  video-server-input-kinds: video
  video-server-output-contract: video-visual-analysis
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-references: references/evidence-synthesis.md, shared/report-writing.md
---
# 综合视频分析

综合分析不是把其他模式各写一小段，而是把镜头事实组织成一条可复核的证据链：先回答画面发生了什么，再回答结构如何变化，最后给出候选价值和下一步制作策略。

## 执行流程

1. 连续覆盖全片，先确认真实编辑边界，再识别连续长镜头内主体任务、空间区域、动作阶段、信息状态或构图任务的有意义重置；两者共同构成分析分镜时间线。
2. 按视觉目标、空间、主体和节奏变化识别内容段落，并将其写入 `scenes`；每个场景连续覆盖相邻镜头且共同完成一个主要任务。
3. 从具体镜头归纳摘要、转折和视觉模式；所有归纳都引用真实 `shot.id`。
4. 分别建立高光候选与资产候选，再检查它们是否覆盖核心段落，而不是简单按数量平均分配。
5. 制作建议按影响、可执行性和连续性风险排序，明确优先镜头和验收条件。

## 工作边界

- 区分观察、解释、建议三种陈述；解释不得冒充事实，建议不得冒充已经执行的决策。
- 同一视觉身份跨镜头合并，状态变化要有画面证据；高光不是最终主选，资产不是已入库版本。
- 摘要应覆盖全片结构，不得只复述最醒目的开头或结尾。
- 不得把“没有检测到 Cut”等同于“整片只有一个分析分镜”。连续阶段边界使用 `transition_in=continuous`，类型无法确认时使用 `unknown`；禁止固定时长切片。
- 无法由画面确认的对白、人物身份、因果、外部背景和传播结果不得补齐。

## 成稿写法

综合分析的读者通常只有几分钟：导语和各段标题就要交代完主线。文字规范见《报告写作规范》，这里只补充本 Skill 的重点。

- `title` 写出全片最核心的判断，例如“前半段靠产品特写建立信任，后半段节奏松散”。
- `summary` 按“这是什么内容 → 结构主线 → 最强之处 → 首要风险”写 2–4 句，每个判断至少点到一个分镜或段落。
- 每个 `scenes[].title` 写成该段完成的事，连起来读就是全片提纲；`description` 写成 2–4 句的小段落，先说这一段做成了什么，再说依据。
- `highlights[].reason` 说明它比同类候选强在哪里，`production_advice.summary` 用一段话说明优先顺序背后的理由，`recommended_extensions` 每条都有分镜依据和可验收的结果。
- 分镜表中的字段会合并成单行，保持简短完整。

证据层级、段落归纳、冲突消解和交付检查见 `references/evidence-synthesis.md`。最终只返回 `video-visual-analysis` Schema。

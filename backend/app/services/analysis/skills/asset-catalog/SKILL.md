---
name: asset-catalog
description: 对角色、场景、道具、产品、Logo 和画面文字做身份归并、状态追踪与证据覆盖。用于可复用视觉资产目录。
license: MIT
metadata:
  video-server-display-name: 资产目录
  video-server-default-prompt: 建立可复用视觉资产目录：基于真实编辑边界与连续视觉节拍做身份归并，记录稳定特征、状态变化、首次出现、关键证据分镜和连续性风险。
  video-server-order: "50"
  video-server-input-kinds: video
  video-server-output-contract: video-visual-analysis
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-references: references/identity-and-state.md, shared/report-writing.md
---
# 视觉资产目录

把视频中的可复用视觉身份整理为稳定目录。核心任务是回答“哪些画面属于同一资产”和“它在何处发生了可见状态变化”，而不是为每个角度、裁切或光照重复建项。

## 执行流程

1. 全片观察后建立临时候选，再根据稳定特征跨分析分镜合并；同一资产贯穿长镜头不代表内部状态变化可以被压进一个分镜。
2. 为每个资产区分身份特征、可变状态、首次出现和最能证明身份的关键镜头。
3. 用 `scenes` 记录资产所处的连续空间和事件段落，地点资产与场景段落保持区分：前者是可复用身份，后者是时间线结构。
4. 对相似但证据不足的对象保持分离或使用保守标签，不强行合并真实身份。
5. 检查核心镜头是否都能回指必要的角色、场景、道具、产品、Logo 或画面文字资产。

## 输出边界

- `type` 只使用 Schema 允许值；`label` 使用稳定、匿名、可检索名称；`description` 分别写稳定特征、状态变化和连续性风险。
- `evidence_shot_ids` 至少覆盖首次清晰出现和关键状态；看不清身份的远景不应成为唯一证据。
- 当前结果是资产身份候选，不是已创建的 Asset、AssetState、AssetVersion、参考图或主选。
- 不从外观推断真实姓名、品牌归属、敏感属性或画面外关系。
- 物理编辑与连续状态阶段都可作为资产证据；连续阶段边界使用 `transition_in=continuous`，类型不明时使用 `unknown`。不得为了增加证据数按固定秒数切片。

## 成稿写法

资产在报告中按“名称 → 类别与首次出现 → 描述”排版，读者会拿它做后续制作的对照表。文字规范见《报告写作规范》，这里只补充本 Skill 的重点。

- `assets[].label` 使用稳定、可检索的中性名称，例如“红色保温杯”“穿灰色外套的男性”，同一资产全文只用一个名称。
- `description` 写成 2–3 句：先写稳定特征，再写可见的状态变化，最后写连续性风险；没有变化或风险时不硬写。
- `summary` 概括资产的数量、构成和最需要锁定一致性的对象。

身份归并、状态记录和证据标准见 `references/identity-and-state.md`。最终只返回 `video-visual-analysis` Schema。

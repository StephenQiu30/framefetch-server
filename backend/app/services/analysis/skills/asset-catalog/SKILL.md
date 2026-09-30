---
name: asset-catalog
description: 对角色、场景、道具、产品、Logo 和画面文字做身份归并、状态追踪与证据覆盖。用于可复用视觉资产目录。
license: MIT
metadata:
  video-server-display-name: 资产目录
  video-server-default-prompt: 建立可复用视觉资产目录：做身份归并，记录稳定特征、状态变化、首次出现、关键证据分镜和连续性风险。
  video-server-order: "50"
  video-server-input-kinds: video
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: video-visual-analysis
  video-server-references: references/identity-and-state.md, shared/report-writing.md
---
# 视觉资产目录

把视频中的可复用视觉身份整理成稳定的目录，核心是回答“哪些画面属于同一资产”和“它在哪里发生了可见的状态变化”，而不是为每个角度、裁切或光照重复建项。读者会拿这份目录做后续制作的对照表。结果是资产身份候选，不是已创建的资产、状态版本、参考图或主选。

## 执行流程

1. 全片观察后建立临时候选，再根据稳定特征跨分镜合并。
2. 为每个资产区分身份特征、可变状态、首次出现和最能证明身份的关键镜头。
3. 用 `scenes` 记录资产所处的连续空间和事件段落。地点资产是可复用身份，场景段落是时间线结构，两者分开。
4. 相似但证据不足的对象保持分离或使用保守标签，不强行合并。
5. 检查核心镜头是否都能回指必要的角色、场景、道具、产品、Logo 或画面文字资产。

## 边界

- `type` 只使用 Schema 允许的值。
- 不从外观推断真实姓名、品牌归属、敏感属性或画面外的关系。
- 分镜边界和资产身份相互独立：切镜不自动产生新资产，同一资产持续存在也不是把不同阶段合成一个分镜的理由。

## 成稿重点

- `summary` 概括资产的数量、构成和最需要锁定一致性的对象。
- `assets[].label` 使用稳定、中性、可检索的名称，例如“红色保温杯”“穿灰色外套的男性”，同一资产全文只用一个名称。

归并顺序、字段写法、证据等级和类型边界见 `references/identity-and-state.md`，通用文字要求见《报告写作规范》。

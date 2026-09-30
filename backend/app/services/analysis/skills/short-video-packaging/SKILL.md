---
name: short-video-packaging
description: 基于视频可见证据生成短视频标题、封面文字、开头钩子和发布文案候选，区分素材事实与创作建议，供发布前人工选用。
license: MIT
metadata:
  video-server-display-name: 短视频包装
  video-server-default-prompt: 观察完整视频，围绕素材实际兑现的主题提供标题、封面文字、开头钩子与发布文案候选，说明各方案的依据与发布前待核验事项。
  video-server-order: "27"
  video-server-input-kinds: video
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: structured-report
  video-server-references: references/packaging-method.md, shared/report-writing.md
---
# 短视频包装

为已经存在的视频提出可供编辑选择的包装草稿。先完整观察素材，确定主题、观众能得到什么，以及视频实际兑现了什么承诺；所有包装都只能承诺素材已经兑现的内容。不生成或发布视频，不调用平台、调度或剪辑工具。

## 边界

- 用户没有指定平台和受众时，给出通用版本，并在 `limitations` 中写明待确认；不推断观众年龄、地域、账号表现或商业效果，也不引用未经核实的平台算法、最佳发布时间或流量说法。
- 没有可靠音频证据时，不声称听到台词、音乐或音效；画面文字也不自动当作已核实的事实。口播钩子只能写成建议文案。
- 观察描述与建议文案分开：前者说明原视频里发生了什么，后者明确是拟新增、需要编辑或补拍的内容。

## 报告结构

报告由服务端按章节编号排版：`body` 是每章的说明段落，`items` 渲染为候选条目，`evidence` 渲染为回看依据。固定使用以下五章：

1. 内容定位（id=positioning）：主题、素材兑现的价值和适用场景，至少一条时间证据。
2. 标题备选（id=titles）：三条不同角度的标题，绑定相关时间证据。
3. 封面文字（id=covers）：两条候选，并指出可用的原视频画面及其时间证据。
4. 开头钩子（id=hooks）：两种方案，每种写清保留或前置的真实画面、拟新增的文字和需要的编辑动作，并绑定素材证据。
5. 发布文案（id=posting-copy）：一段准确的简介和一个与内容相关的互动问题；本章可以没有 evidence。

## 成稿重点

- `title` 写出本次包装的方向，例如“围绕‘三步去除咖啡渍’的标题与封面方案”，不写“短视频包装报告”。
- `summary` 用 2–3 句交代核心主题、素材最能兑现的价值、最需要人工确认的前提。
- 每章 `body` 写 1–2 个短段落，先说本章的取舍原则，再说依据，不复述条目。
- 缺少支撑时减少候选并说明原因，不为凑数制造事实。`limitations` 写明音频缺口、平台与受众假设，以及身份、数字、画面文字等发布前需要核实的事项。

标题、封面、钩子和文案的具体方法见 `references/packaging-method.md`，通用文字要求见《报告写作规范》。最终只返回 structured-report 契约要求的 JSON。

---
name: continuity-quality-review
description: 对已渲染成片执行可见连续性与交付质量审查，覆盖主体状态、空间方向、动作衔接、画面文字、图形一致性和明显技术瑕疵。
license: MIT
metadata:
  video-server-display-name: 连续性与成片 QA
  video-server-default-prompt: 以交付前看片的方式完整审查成片，检查主体状态、空间方向、动作衔接、图形文字，以及可见的黑帧、闪烁、拉伸或遮挡问题。
  video-server-order: "47"
  video-server-input-kinds: video
  video-server-modules: drama-blocking-playbooks, humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: video-visual-analysis
  video-server-references: references/continuity-qa-rubric.md, shared/report-writing.md
---
# 连续性与成片 QA

这是一份交付前看片的审查报告：把可见问题定位到时间轴上，区分确定缺陷、需要人工复核的风险和成立的连续性锚点。读者先要知道能不能交付，再看具体问题。报告是审查清单，不自动修改或批准成片。

## 上游方法的用法

上文 drama-blocking-playbooks 的轴线与屏幕方向、单房调度、证据揭示和观察视角一节，在这里用作切换前后的比对清单：位置与朝向、左右手与道具、伤势与造型、轴线与运动方向、门灯天气与文字状态。上游提到的关键帧、资产版本和提示词不属于本任务。没有可靠音频证据时，依赖声音的条目不评价。

## 工作方法

1. 建立完整的分镜与段落，比较相邻分镜的主体身份、服装道具与界面状态、空间关系、屏幕方向、动作起止和光色规则；长镜头内部的状态漂移单独成镜，不藏在一条描述里。
2. 检查画面文字与图形的可辨性、裁切、遮挡、对比度、样式漂移和安全区风险；看不清的文字只标记人工复核，不猜内容。
3. 记录可见的黑帧、意外冻结、闪烁、比例拉伸、边缘穿帮、突兀的分辨率变化或合成遮挡，但不声称完成了逐帧编码检测。
4. 每个问题都写出位置、观察、影响和验收条件；没有明确缺陷时建议可以很少，不为填满报告制造问题。

## 边界

不评价爆音、响度、同步、底噪、音乐或对白；不执行文件修复、发布或外部审查。严重度表达相对修复优先级，不等同于法律、品牌或发布批准。

## 成稿重点

- `title` 直接写审查结论，例如“未见阻断问题，两处屏幕方向需要人工复核”。
- `summary` 先写是否存在阻断理解或交付的可见问题，再写主要的连续性模式和观察局限。
- `highlights` 只用于呈现连续性保持得特别好、值得复用的候选，不把“没有缺陷”伪造成高分。

检查面、严重度、字段写法和自检见 `references/continuity-qa-rubric.md`，通用文字要求见《报告写作规范》。

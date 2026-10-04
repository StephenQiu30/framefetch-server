---
name: video-review
description: 围绕用户的观看目标审阅成片的叙事、镜头、剪辑与连续性，给出有定位的优先修改和保留理由。
license: MIT
metadata:
  video-server-display-name: 成片审阅
  video-server-default-prompt: 找出最影响观众理解或观看体验的具体问题与值得保留的表达；按影响排序，写清位置、原因和修改目标，不凑问题数量。
  video-server-order: "10"
  video-server-input-kinds: video
  video-server-output-contract: structured-report
  video-server-modules: drama-edit-cut-craft, drama-shot-grammar, drama-blocking-playbooks, zh-copywriting-guidelines
---

# Plan

先识别作品想让观众理解、感受或决定什么，沿完整时间轴观察，再根据真实问题选择叙事、镜头动机、剪辑节奏或连续性的方法。复看问题前后的上下文，区分有意留白、铺垫和理解缺口。记录优先判断及需要复核的位置。

# Draft

先交付整体判断，再写真正需要处理的问题和值得保留的机制。每项问题说明位置、观众会怎样理解、因果原因及修改目标。没有重大问题允许直接说明成片已经成立。不要套四维评分、强制优缺点数量或通用建议。sections 只承载本片需要的内容，不再同时交付分镜、高光和资产目录。

# Review

对照视频核实位置和描述，检查是否误将主观偏好、缺少音频或采样局限当成制作缺陷。删除适用于任意视频的建议；用户目的之外的意见只在影响成立时保留。重大问题要有具体修正目标，合理表达无需修改。不得预测留存率或市场表现。

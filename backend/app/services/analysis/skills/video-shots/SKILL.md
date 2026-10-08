---
name: video-shots
description: 使用 reelbench 原生脚本实测切点、时长和运动曲线，以每镜起手与收尾画面做逐镜标注，生成拉片表与原生互动报告。
license: Apache-2.0
metadata:
  framefetch-server-display-name: 逐镜拉片
  framefetch-server-default-prompt: 按实际镜头解释景别、运镜、画面与节奏作用；保留机器实测边界，指出画面依据和检测局限，不编造声音。
  framefetch-server-order: "30"
  framefetch-server-input-kinds: video
  framefetch-server-output-contract: structured-report
  framefetch-server-upstream: reelbench:skills/video-shots/SKILL.md
---

# Purpose

服务端运行完整固定版本 reelbench 脚本，冻结 seed、运动曲线、每镜两张关键帧与联系表。模型仅标注画面，不执行脚本，不改机器字段，不发布内容。

先完整阅读 references/taxonomy.md 与 references/analysis-pass.md。每次只处理给定镜号，联系表依镜号按行排列；两张图分别为起手和收尾。取景变化与主体运动分开判断，实测运动不等于摄影机运动。不得声称听见声音；烧录字幕可引用，其他声音留空。cast 未可靠建立时 subjects 保持空，主体仍应在 frame 具体描述。没有节奏证据时不强行制造 hook 或 payoff。

最终 JSON 只含本批次的视觉标注字段。服务端合并到原始 seed，再用完整运动曲线与关键帧执行原生 validate；未通过不得发布。脚本检测边界不代表全部真实剪切已确认，尤其软转场仍须人工复核。当前全片最多 100 个检测镜头，超限明确失败，不裁掉后半段。

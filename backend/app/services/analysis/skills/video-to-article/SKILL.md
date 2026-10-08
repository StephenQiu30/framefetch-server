---
name: video-to-article
description: 根据实测视频材料，以 ECC article-writing 完整方法策划和撰写公众号文章，独立审校后使用 baoyu 原生排版生成可导出的 HTML。
license: MIT
metadata:
  framefetch-server-display-name: 公众号成稿
  framefetch-server-default-prompt: 把视频中可核查的内容整理为能独立阅读的公众号文章；先确定读者问题与角度，再用具体画面证据推进，避免时间线流水账和空泛结论。
  framefetch-server-order: "40"
  framefetch-server-input-kinds: video
  framefetch-server-output-contract: video-article
  framefetch-server-upstream: reelbench:skills/video-shots/SKILL.md, ecc:skills/article-writing/SKILL.md, baoyu:skills/baoyu-format-markdown/SKILL.md, baoyu:skills/baoyu-markdown-to-html/SKILL.md, drama:skills/short-drama-review/SKILL.md
---

# Purpose

先读完整 ECC 写作方法与适用的 baoyu 排版参考。服务端提供同一源文件实测切点、时长与运动曲线，模型通过受控观察工具核对画面；机器测量不代替视觉理解。正文只写材料支持的事实，未提供音频转写不能编造对白。上游安装、写文件、发布与联网步骤由产品边界约束，模型不执行。最终正文由服务端按原生 baoyu Markdown renderer 确定性排版，发布到本任务私有报告；不向公众号发送。

# Plan

以 ECC 方法确定读者问题、中心角度、论证推进和舍弃内容。先覆盖完整时间轴，再列出需要复看的位置。只看见画面中的声明时保留来源归属；没有足够内容写长文时选择短文，不补外部事实。

# Draft

按计划撰写完整文章。标题具体，段落之间有承接，正文可脱离视频阅读，不按镜号逐条复述。sections 内只保存文章纯文本；证据和局限独立保存，不写入文章文件。正文可短，不为填满字段制造导语、结尾和要点。没有可靠声音证据时不把视觉分析写成视频逐字稿。

# Review

独立核对文章的中心判断、事实归属、段落推进和画面证据，使用完整 short-drama-review 的反证与抗模板方法。保留成立的表达；只报告影响阅读或事实准确性的具体问题，不把上游影视评分表硬套到文章。重大问题必须给出位置、证据和修改目标，定点修订不能新增未经核查的事实。不能把模型审校称为微信编辑器兼容性验收。

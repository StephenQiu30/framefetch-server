---
name: screenplay-continuity-review
description: 审阅完整剧本中跨场景的人物知识、物件状态、时空顺序和因果连续性，区分真实矛盾与有意留白。适用于中文或英文剧本。
license: MIT
metadata:
  video-server-display-name: 剧本连续性审阅
  video-server-default-prompt: 检查人物知情、时间地点、道具状态、伏笔兑现和跨场景因果。只报告剧本文本明确支持的问题，并给出可执行的修订目标。
  video-server-order: "75"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-analysis
  video-server-modules: drama-review-method, drama-story-script, humanizer-zh, zh-copywriting-guidelines
  video-server-references: references/continuity-rules.md, shared/report-writing.md, shared/screenplay-coverage-writing.md
---

# 剧本连续性审阅

按源场景顺序建立人物、信息、物件、时间与空间状态，再检查后续场景是否有可追溯的变化。直接加载上游短剧审稿方法与故事剧本量表的指定章节；其跨文档、owner 和文件交付流程不适用于本任务。审阅的是上传剧本的 editorial coverage；不要修改原文、生成分镜、估算镜头数量或宣布制作资产已确认。

## 工作方法

1. 每个 `source_scene_id` 都要有逐场景结果。记录该场进入时的状态、可观察动作和离开时改变的状态；没有充分信息时明确未知。
2. 对跨场景问题写清矛盾两端已经建立的文本状态。缺少过渡信息与文本明确矛盾应分别表述；悬念、误导、主观叙述和有意省略不能直接判作错误。
3. 人物“知道什么”只能由其可见行动、对白或可靠叙述支持。角色知识、观众知识与故事世界事实分别判断。
4. 道具、伤势、服装、空间位置、时间和关系状态只在文本建立过且影响理解时追踪；不补造生产清单。
5. 对每个有文本支持的问题说明观众会在哪里失去因果理解，以及作者需要恢复的最小状态或过渡。修改建议保持创作选择开放。
6. 使用 `screenplay-analysis` JSON 契约：逐场问题写入 `scenes[].findings`，跨场问题写入 `priority_revisions`，对白引发的信息矛盾可写入 `dialogue_findings`。其他必填字段简洁且只根据上传文本，不增加新字段。
7. 长剧本分块时只判定本块能说明的事实；汇总时综合分块中的文本状态检查跨块连续性，不把缺少上下文当成错误。

详细规则见 [continuity-rules](references/continuity-rules.md)。

## 成稿写法

报告面向要动手修改的作者：先读到该改什么，再读到依据。各字段在报告中的位置和写法见《剧本审稿报告写法》，通用文字规范见《报告写作规范》；上游写作模块只用于自查成稿表达，不改变审稿结论与输出契约。

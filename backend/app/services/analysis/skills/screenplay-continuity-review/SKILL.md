---
name: screenplay-continuity-review
description: 审阅完整剧本中跨场景的人物知识、物件状态、时空顺序和因果连续性，区分真实矛盾与有意留白。适用于中文或英文剧本。
license: MIT
metadata:
  video-server-display-name: 剧本连续性审阅
  video-server-default-prompt: 检查人物知情、时间地点、道具状态、伏笔兑现和跨场景因果，只报告剧本文本明确支持的问题，并给出可执行的修订目标。
  video-server-order: "75"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-analysis
  video-server-modules: drama-story-script, humanizer-zh, zh-copywriting-guidelines
  video-server-references: references/continuity-rules.md, shared/report-writing.md, shared/screenplay-coverage-writing.md
---

# 剧本连续性审阅

按源场景顺序建立人物、信息、物件、时间与空间的状态，再检查后续场景是否有可以追溯的变化。上文 drama-story-script 中关于世界事实、人物信念与观众知情分离、证据载体和连续记忆的问题，是这里的主要判断工具。审阅对象是上传的剧本本身，不修改原文、不生成分镜、不估算镜头数量，也不宣布制作资产已经确认。

## 工作方法

1. 每个源场景都有逐场结果：记录该场进入时的状态、可观察的动作和离开时改变的状态；信息不足时明确写未知。
2. 跨场问题写清矛盾两端已经建立的文本状态。缺少过渡信息和文本明确矛盾要分开表述；悬念、误导、主观叙述和有意省略不能直接判为错误。
3. 人物“知道什么”只能由其可见的行动、对白或可靠叙述支持；角色知识、观众知识和故事世界的事实分别判断。
4. 道具、伤势、服装、空间位置、时间和关系状态，只在文本建立过且影响理解时追踪，不补造生产清单。
5. 对每个有文本支持的问题，说明观众会在哪里失去因果理解，以及作者需要恢复的最小状态或过渡，保持创作选择开放。
6. 长剧本分块时只判定本块能说明的事实；汇总时综合各块的文本状态检查跨块连续性，不把缺少上下文当成错误。

## 输出分工

逐场问题写入 `scenes[].findings`，跨场问题写入 `priority_revisions`，对白引发的信息矛盾可写入 `dialogue_findings`；其他必填字段简洁且只依据上传文本。判定边界见 `references/continuity-rules.md`，字段写法见《剧本审稿报告写法》，通用文字要求见《报告写作规范》。只返回 `screenplay-analysis` JSON。

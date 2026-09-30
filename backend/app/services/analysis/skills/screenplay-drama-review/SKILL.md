---
name: screenplay-drama-review
description: 基于 drama-skills 短剧审稿量表，检查故事承诺、人物选择、局部回报、连续记忆和重复机制。
license: MIT
metadata:
  video-server-display-name: 短剧故事审稿
  video-server-default-prompt: 重点审查故事承诺、每个段落的局部结果、人物选择与代价，以及重复情节是否真正改变意义。
  video-server-order: "61"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-analysis
  video-server-modules: drama-story-script, drama-anti-template, humanizer-zh, zh-copywriting-guidelines
  video-server-references: shared/report-writing.md, shared/screenplay-coverage-writing.md
---

# 短剧故事审稿

用上文 drama-story-script 的故事承诺、人物记忆、场景测试和对白问题，以及 drama-anti-template 的四层诊断与误报反例，审阅本次上传的剧本。先确认文本明确的事实，再判断故事承诺、人物行动、局部结果和重复机制。

## 审阅重点

1. 故事引擎能否产生不同的压力，还是每一轮都重复同一种误会、羞辱、营救或揭示。
2. 每个段落是否让权力、信息、关系、暴露程度、代价或时间发生变化。
3. 人物声称的变化是否经过压力测试、选择、局部结果和代价，并改变了之后可见的策略。
4. 重复只有在能指出至少两个位置、并说明损失了什么意义时才判为模板化；仪式性重复、喜剧梗、人物口癖和类型惯例按误报反例处理。

## 边界

- 上游量表中的文件、记录编号、owner、状态和跨文档流程不属于本任务，不在结果中出现。
- 分集量表只在文本本身是分集短剧时使用；长片、单集或非传统结构不要求固定钩子、节拍、页数或结尾形态。
- 只把充分成立且影响大的问题放入 `priority_revisions`，没有依据时留空。每个源场景恰好覆盖一次，内部场景 ID 不是证据。

字段写法见《剧本审稿报告写法》，通用文字要求见《报告写作规范》。只返回 `screenplay-analysis` JSON。

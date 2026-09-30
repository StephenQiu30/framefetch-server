---
name: screenplay-rewrite
description: 执行中文和英文剧本的跨语言改写或同语言润色，并保持场景、人物、事实与术语一致。用于 zh-CN 和 en-US 剧本改写任务。
license: MIT
metadata:
  video-server-display-name: 剧本中英改写
  video-server-default-prompt: 在不改变情节事实和场景顺序的前提下完成中英文改写或同语言润色，并保持人物声音与术语一致。
  video-server-order: "80"
  video-server-input-kinds: screenplay
  video-server-output-contract: screenplay-rewrite
  video-server-modules: zh-copywriting-guidelines
  video-server-references: references/rewrite-rules.md
---

# 剧本中英改写

按源场景顺序改写中文或英文剧本。目标语言由任务参数确定：与源语言不同时做忠实的本地化，相同时做表达润色。改写结果是新的不可变文本版本候选，不覆盖原稿，也不改动资产、镜头、主选或审稿结论。不得改变故事事实、场景数量或角色身份。

## 工作规则

1. 保留源场景 ID、顺序、标题语义、角色名、动作因果和关键信息；不新增或删除情节。
2. 先建立人名、地名、称谓、组织、专有物件和反复意象的 glossary，再在所有块中一致使用。glossary 只记录跨场景需要稳定复用的名称，不当作资产清单，也不新增原文没有的实体。
3. 对白符合目标语言的自然表达，同时保留人物声音、关系、潜台词、打断和情绪强度。
4. 每个 chunk 只对应一个源场景及其连续的 part，携带受控流程给出的 `source_sha256`；不自行改写标识或哈希。
5. 所有源场景必须且只能覆盖一次，块按场景和 part 顺序返回；不返回另一份独立全文。
6. 分段调用只是传输边界，不是新增场景或镜头；不把段落、对白块或 chunk 改写成新的 `source_scene_id`，也不在 change summary 里声称已经拆镜或完成审稿。

## 成稿写法

- 目标为中文时，舞台指示和叙述按上文 zh-copywriting-guidelines 处理空格、全角标点和专有名词大小写；人物有意为之的口语、方言和不规范表达保留原样，不用书面排版规范去“修正”台词。
- `change_summary` 每条是一个完整的句子，说明改了哪一类内容、为什么改、涉及哪些场景，例如“把‘老板’统一译为 boss，保留两人之间的随意语气，涉及全部办公室场景”；不写“优化了表达”“提升了流畅度”这类没有信息的总结。
- glossary 中确定的译名，正文和 change summary 都使用同一种写法。

语言策略、一致性与覆盖规则见 `references/rewrite-rules.md`。只返回 `screenplay-rewrite` 契约要求的 glossary、chunks 和 change summary，不输出工具调用、外部链接或 Markdown 报告。

# screenplay-analysis 输出契约

## 顶层结构

完整场景调用必须返回以下字段，字段名不能翻译、增加或删除：

```json
{
  "language": "zh-CN 或 en-US",
  "title": "...",
  "logline": "...",
  "synopsis": "...",
  "structure": {
    "acts": [],
    "turning_points": [],
    "pacing_summary": "..."
  },
  "characters": [],
  "scenes": [],
  "dialogue_findings": [],
  "strengths": [],
  "priority_revisions": []
}
```

汇总调用使用同一份全局结构，但不返回 `scenes`；执行器会把已经校验的分块场景结果合并回最终结果。

## ID 与场景覆盖

- 所有 `id` 都是不含空白的稳定字符串，例如 `act-01`、`turn-01`、`character-01`、`scene-analysis-0001`、`finding-01`；同一数组内不得重复。
- `source_scene_id` 必须逐字复制请求提供的 ID，只能来自权威列表，不得创建 `scene-1`、`场景一` 等替代名称。
- `scenes` 中每项只对应一个源场景，并按输入列表的原顺序出现：

```json
{
  "id": "scene-analysis-0001",
  "source_scene_id": "scene-0001-abc123",
  "purpose": "本场在故事中的功能",
  "conflict": "本场的目标与阻力",
  "turn": "本场结束时发生的可验证变化；没有变化就明确说明",
  "pacing": "节奏判断及其依据",
  "findings": ["本场独有的具体发现"]
}
```

这里的 `scenes` 是对源文本场景的逐项审阅，不是视频分析中的 `shots`，也不是未来的生产分镜。不填入模型自造的镜头数量、Cut 编号或固定时长拆分。

## 分析条目

`acts`、`turning_points`、`dialogue_findings`、`strengths` 和 `priority_revisions` 使用相同形状：

```json
{
  "id": "finding-01",
  "title": "一句判断",
  "description": "文本依据、影响与目标"
}
```

`acts` 至少返回一项。`turning_points`、`dialogue_findings`、`strengths` 和 `priority_revisions` 没有独立、可说明的发现时返回空数组，不为填充数组而重复或臆测。`priority_revisions` 按对理解、因果和人物选择的影响排序。

## 人物条目

```json
{
  "id": "character-01",
  "name": "原文中的人物名",
  "goal": "外部目标或稳定欲望",
  "conflict": "阻力、矛盾或关系压力",
  "arc": "选择、结果和变化；静态人物说明其稳定立场如何影响故事"
}
```

只列出对故事有独立作用的主要人物；临时群众、背景人物和只出现一次且没有叙事作用的名字不必单列。

## 文本格式

字段内容是纯文本，不嵌套 Markdown 标题、表格、代码围栏、HTML、链接或整段原文。`synopsis`、`pacing_summary` 和条目的 `description` 可以用换行分段，其余字段写成单段。

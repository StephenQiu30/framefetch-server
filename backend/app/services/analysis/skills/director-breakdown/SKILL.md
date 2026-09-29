---
name: director-breakdown
description: 按真实编辑边界与连续镜头节拍复盘调度、构图、镜头动机、剪辑关系和复刻策略。用于完整视频的专业导演拉片。
license: MIT
metadata:
  video-server-display-name: 导演拉片
  video-server-default-prompt: 以导演工作台方式逐分镜拉片，区分真实 Cut 与连续长镜头内的视觉节拍，复盘调度、镜头动机、剪辑关系、连续性和可执行复刻策略。
  video-server-order: "10"
  video-server-input-kinds: video
  video-server-modules: drama-skills-short-drama-storyboard-shot-craft, drama-skills-short-drama-storyboard-production-shot-grammar, drama-skills-short-drama-storyboard-blocking-playbooks
  video-server-output-contract: video-visual-analysis
  video-server-references: references/director-method.md
---
# 导演拉片

目标不是罗列景别，而是解释每个分析分镜为什么成立、画面如何组织注意力、相邻分镜如何共同完成一个叙事节拍，以及这些观察如何转成可执行的复刻方案。分析分镜既可以来自物理编辑，也可以来自连续长镜头内已经完成并切换任务的视觉阶段。

## 引用方法的用法

上文的 Source module 是固定版本的上游方法，原本写给分镜与剪辑制作流程。这里只把其中的判断标准用于审阅已经完成的视频：
- 只评价画面中可见的决策，不输出分镜稿、剪辑单、关键帧或生成提示词，也不涉及其中提到的项目文件、字段、工具或下游环节。
- 当前没有可靠音频证据：凡是依赖台词发声、音乐、音效或声音桥的条目一律不评价，必要时在局限中说明。
- 上游示例与数字（如镜长、景别阶梯）是参考而非配额；结论必须回到本片的真实分镜证据。

## 执行顺序

1. 先全片覆盖，再复核疑似边界；分别标记物理 Cut/转场和连续镜头内的语义节拍。低对比转场、遮挡转场和显著画面演化不能只靠固定阈值判断，也不能因没看到 Cut 就把长片合成一镜。
2. 对每镜分别记录可见事实、主体调度、构图/光色、摄影机行为、剪辑关系和叙事功能，禁止用风格形容词替代观察。
3. 纵向检查镜头序列，并把连续完成同一任务的相邻镜头归入 `scenes`：空间建立、视线/运动方向、动作衔接、景别变化、节奏转折和视觉母题。
4. 最后才评高光、资产和复刻优先级；场景、高光、资产和建议必须能回指真实 `shot.id`。

## 输出纪律

- `description` 按“主体与动作；空间与构图；光线与色彩；镜头起止状态”写可见事实。无法从画面确认焦段、机位尺寸或创作者意图时不要猜。
- 物理编辑使用对应的 `transition_in`；确认无编辑但进入新视觉阶段时使用 `transition_in=continuous`；边界成立但转场类型不明时使用 `unknown`。不得按固定秒数切片。
- `narrative_function` 写“本镜头完成的节拍 + 与前后镜头的关系 + 判断依据”，不要只写“推进剧情”“营造氛围”。
- `visual_tags` 使用参考文档中的受控前缀，保留角度、构图、光色、连续性和节奏线索。
- 高光分数只是本次分析中的相对排序；资产只是身份候选；`production_advice` 只是制作建议，均不代表主选、审核或项目写入结果。
- 没有可靠音频证据时，不得把字幕、口型或画面文字推断成对白、音乐、音效或作者观点。

详细判读步骤、字段映射和交付自检见 `references/director-method.md`。最终只返回 `video-visual-analysis` Schema 所需字段。

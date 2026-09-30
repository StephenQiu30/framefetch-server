---
name: visual-shots
description: 把真实编辑边界与连续镜头节拍整理为可复核、可交接的分镜表，覆盖起止状态、主体动作、构图、光色、边界、连续性和制作提示。
license: MIT
metadata:
  video-server-display-name: 分镜表制作
  video-server-default-prompt: 制作专业反向分镜表，区分真实 Cut 与连续长镜头内的视觉节拍，逐段记录起止状态、主体动作、构图、机位与运动、光色、边界和连续性锚点。
  video-server-order: "30"
  video-server-input-kinds: video
  video-server-output-contract: video-visual-analysis
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-references: references/storyboard-table.md, shared/report-writing.md
---
# 分镜表制作

输出的是基于成片观察的“反向分镜表”，不是按固定秒数抽样的截图清单，也不是已经创建的生产镜头。每一行必须让导演、剪辑或生成团队在不回看片段的情况下，理解画面起点、动作变化、结束状态和相邻镜头的衔接约束。

## 核心要求

1. 全片初扫后分别复核真实 Cut/转场与连续镜头内的视觉节拍；每个分析分镜至少比较起始、代表和结束画面。低对比转场、遮挡切换、屏幕内容更新和同镜头内任务变化都要语义复核。
2. `description` 使用统一四段格式；`narrative_function` 说明镜头任务及其衔接；`visual_tags` 承载角度、构图、光色和连续性等可排序维度。
3. 同一动作跨 Cut 时，上一镜的结束状态应能与下一镜的开始状态对上；无法对上时明确标为连续性风险，而不是虚构缺失动作。
4. `scenes` 将相邻分镜归并成连续场景段落，逐场记录稳定视觉规则和连续性风险；全部场景必须覆盖所有镜头一次。
5. `assets` 合并同一视觉身份，`highlights` 只保留值得重点复刻或审阅的候选；两者均引用真实镜头。
6. 视觉观察不能替代剧本、对白或音频事实。字幕和画面文字只能作为可见元素记录。
7. 连续镜头内发生主体任务、空间区域、动作阶段、信息状态或构图任务重置时，应建立新的分析分镜并使用 `transition_in=continuous`；边界类型不明用 `unknown`。不得按固定秒数拆分，也不得让持续运镜本身成为拆分理由。

## 成稿写法

分镜表是报告主体，但表前的导语和场景段落决定读者能否快速定位。文字规范见《报告写作规范》，这里只补充本 Skill 的重点。

- `title` 概括全片的镜头组织方式，例如“12 个分析分镜：一组跟拍贯穿，两次硬切换场”。
- `summary` 交代分镜总体结构、最需要交接注意的衔接点和采样局限。
- 分镜字段会进入表格单元格，换行会被合并：`description` 按四段格式写成一句，用分号隔开，控制在 120 字以内；`narrative_function` 一句话写清镜头任务和与前后镜头的衔接，不写“推进剧情”。
- `scenes[].description` 写成连续的小段落，说明该段的起止状态和衔接约束；`visual_rules` 每条写成可以直接照做的规则。

字段格式、标签词表、连续性检查和验收规则见 `references/storyboard-table.md`。最终只返回 `video-visual-analysis` Schema 所需字段。

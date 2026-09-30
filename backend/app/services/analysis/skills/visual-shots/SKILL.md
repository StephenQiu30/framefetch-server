---
name: visual-shots
description: 把真实编辑边界与连续镜头节拍整理为可复核、可交接的反向分镜表，覆盖起止状态、主体动作、构图、光色、边界、连续性和制作提示。
license: MIT
metadata:
  video-server-display-name: 分镜表制作
  video-server-default-prompt: 制作反向分镜表，逐段记录起止状态、主体动作、构图、机位与运动、光色、边界和连续性锚点。
  video-server-order: "30"
  video-server-input-kinds: video
  video-server-modules: humanizer-zh, zh-copywriting-guidelines
  video-server-output-contract: video-visual-analysis
  video-server-references: references/storyboard-table.md, shared/report-writing.md
---
# 分镜表制作

交付物是基于成片观察的反向分镜表，不是按固定间隔抽样的截图清单，也不是已经创建的生产镜头。每一行都要让导演、剪辑或生成团队不回看片段也能理解画面起点、动作变化、结束状态和相邻镜头的衔接约束。

## 核心要求

1. 全片初扫后分别复核真实 Cut、转场和连续镜头内的视觉节拍；每个分析分镜至少比较起始、代表和结束画面。低对比转场、遮挡切换、屏幕内容更新和同一镜头内的任务变化都要语义复核。持续运镜本身不是拆分理由。
2. 同一动作跨 Cut 时，上一镜的结束状态应与下一镜的开始状态对得上；对不上时写成连续性风险，不虚构缺失的动作。
3. `scenes` 把相邻分镜归并成连续段落，逐段记录稳定的视觉规则和连续性风险。
4. `assets` 合并同一视觉身份，`highlights` 只保留值得重点复刻或审阅的候选。
5. 字幕和画面文字只作为可见元素记录，不当作对白或音频事实。

## 成稿重点

- `title` 概括全片的镜头组织方式，例如“12 个分析分镜：一组跟拍贯穿，两次硬切换场”。
- `summary` 交代分镜的总体结构、最需要交接注意的衔接点和观察局限。
- 分镜表是报告主体，但段落描述决定读者能否快速定位：每个 `scenes[].description` 写成连续的小段落，`visual_rules` 每条都是可以直接照做的规则。

字段写法、标签词表、连续性检查和制作建议见 `references/storyboard-table.md`，通用文字要求见《报告写作规范》。

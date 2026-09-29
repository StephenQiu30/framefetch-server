---
name: continuity-quality-review
description: 对已渲染成片执行可见连续性与交付质量审查，覆盖主体状态、空间方向、动作衔接、画面文字、图形一致性和明显技术瑕疵。
license: MIT
metadata:
  video-server-display-name: 连续性与成片 QA
  video-server-default-prompt: 以交付前看片方式完整审查成片，区分真实编辑边界与连续长镜头节拍，检查主体状态、空间方向、动作衔接、图形文字和可见黑帧、闪烁、拉伸或遮挡问题。
  video-server-order: "47"
  video-server-input-kinds: video
  video-server-modules: drama-skills-short-drama-storyboard-blocking-playbooks
  video-server-output-contract: video-visual-analysis
  video-server-references: references/continuity-qa-rubric.md
---
# 连续性与成片 QA

目标是像交付前看片一样，把可见问题定位回真实时间轴，并区分确定缺陷、需要人工复核的风险与成立的连续性锚点。该结果是审查清单，不自动修改或批准成片。

## 引用方法的用法

上文的 Source module 是固定版本的上游方法，原本写给分镜与剪辑制作流程。这里只把其中的判断标准用于审阅已经完成的视频：
- 只评价画面中可见的决策，不输出分镜稿、剪辑单、关键帧或生成提示词，也不涉及其中提到的项目文件、字段、工具或下游环节。
- 当前没有可靠音频证据：凡是依赖台词发声、音乐、音效或声音桥的条目一律不评价，必要时在局限中说明。
- 上游示例与数字（如镜长、景别阶梯）是参考而非配额；结论必须回到本片的真实分镜证据。

## 工作方法

1. 建立包含真实编辑边界与连续视觉节拍的完整分镜和场景覆盖，比较相邻分析分镜的主体身份、服装/道具/界面状态、空间关系、屏幕方向、动作起止和光色规则；不要把长镜头内部状态漂移隐藏在单一条目中。
2. 检查画面文字与图形的拼写可辨性、裁切、遮挡、对比度、样式漂移和安全区风险；看不清的文字只标记人工复核，不猜内容。
3. 记录可见黑帧、意外冻结、闪烁、比例拉伸、边缘穿帮、突兀分辨率变化或合成遮挡，但不声称完成逐帧编码检测。
4. 用 `qa:critical`、`qa:major`、`qa:minor` 表达相对修复优先级，并说明影响范围；严重度不等同于法律、品牌或发布批准。
5. 每项建议包含真实 `shot.id`、观察、影响和验收条件；没有明确缺陷时允许建议较少，不为填满报告制造问题。

## 输出边界

- `summary` 先写是否存在阻断理解或交付的可见问题，再写主要连续性模式与采样局限。
- `continuity_risks` 记录场景内或场景间可复核风险；`visual_rules` 记录应保持的稳定锚点。
- `highlights` 只用于呈现成功保持连续性或特别值得复用的候选，不把“无缺陷”伪造成高分。
- 无可靠音频证据时不评价爆音、响度、同步、底噪、音乐或对白；不执行文件修复、发布或外部审查。
- 连续镜头内进入新的可复核状态阶段时使用 `transition_in=continuous`，边界类型不明时使用 `unknown`。评估连续边界时不得把物理 Cut 的有意省略与连续运动中的突变混为一类。

检查面、严重度和字段映射见 `references/continuity-qa-rubric.md`。最终只返回 `video-visual-analysis` Schema。

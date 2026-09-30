# 分镜表字段规范

## 一、每镜观察点

每个分析分镜至少核对三帧：

- **起始帧**：物理转场完成后的第一个稳定画面，或连续节拍中能证明任务已经重置的画面，确定主体、空间和动作起点。
- **代表帧**：最能表达构图与镜头任务的画面，时间写入 `representative_frame_ms`，优先核心构图而不是转场残帧。
- **结束帧**：切出前的最后稳定状态，记录动作、道具、朝向和光线。

连续长镜头内出现已完成的屏幕状态、主体任务、空间区域、动作阶段或构图任务重置时，拆成新的分析分镜；变化只是同一任务的连续过程时，在描述中写出过程。

## 二、分镜行写法

报告会把每个分镜排成表格的一行：时码、时长、画面内容、景别 / 运镜 / 边界、镜头作用、重要度。字段写法如下：

- `description`（画面内容）：一到两句连贯的中文，依次交代主体与动作、空间与构图、光线与色彩、起止状态，通常 60–150 字。不加“主体与动作：”这类标签，不写设备参数。例如：“店员把样品从柜台下方举到画面中央，背景货架虚化成暖色色块；顶光在瓶身留下一道高光；镜头从空柜台开始，停在样品正对镜头。”
- `shot_size`、`camera_motion`、`transition_in`：使用 Schema 枚举，报告会译成“中景 / 固定 / 硬切”。
- `narrative_function`（镜头作用）：一句话写清本镜的任务和与相邻镜头的衔接，例如“把观众视线从店员交到产品上，为下一镜的标签特写做准备”。
- `highlight_score`（重要度）：1–5，表示本镜对全片的视觉或叙事价值。
- `visual_tags`：不进入报告正文，用于检索和排序，见下节。

## 三、受控标签

标签使用 `维度:值`，只保留能从画面确认的值：

- `angle:` eye-level / high / low / overhead / dutch / pov / over-shoulder / unknown
- `composition:` centered / rule-thirds / symmetry / leading-lines / frame-within-frame / negative-space / layered / silhouette
- `lighting:` high-key / low-key / side / back / rim / practical / soft / hard / mixed
- `palette:` warm / cool / neutral / monochrome / complementary / accent-color
- `continuity:` screen-direction / eyeline / action / prop-state / costume / lighting / geography / text-state
- `rhythm:` hold / reveal / acceleration / deceleration / interruption / montage
- `segmentation:` single-unit-verified（仅用于超过 10 秒、完整复核后仍确认为单一分析分镜的素材）

不写 `cinematic`、`beautiful`、`高级感` 等不可复核的词。

## 四、连续性检查

逐镜扫描：

1. **空间**：建立镜头是否让人物和关键物的相对位置可理解。
2. **方向**：视线、移动方向和出入画方向在相邻镜头之间是否衔接。
3. **动作**：上一镜的结束动作与下一镜的开始动作是否一致；跳跃是有意省略还是证据不足。
4. **状态**：道具的手别和位置、服装、屏幕文字、门窗开合、破损和光线是否稳定。
5. **构图变化**：景别、角度或运动的变化是否为节拍服务；不机械套用 30 度或 180 度规则。
6. **时长**：分镜区间准确相加到权威总时长。

发现问题时写入所在段落的 `continuity_risks`，每条写成一个完整句子：位置、问题和影响，例如“分镜 007 到 008 之间杯子从左手换到右手，没有交代换手动作，复刻时会让观众以为少了一镜”。

## 五、制作建议

`production_advice` 给出反向复刻方法，而不是泛泛评价：优先分镜、必须锁定的连续性锚点、建议拆分的复杂动作、适合用固定帧控制的起止状态，以及验收条件。`recommended_extensions` 每条是完整句子，正文中写“分镜 004”，不写内部 ID。

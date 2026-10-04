---
name: video-breakdown
description: 按用户用途拆出镜头、场景或资产记录，用可回看的位置组织素材；只交付所选的整理结果。
license: MIT
metadata:
  video-server-display-name: 素材拆解
  video-server-default-prompt: 按我的用途整理素材。默认按叙事片段列出内容与位置；需要分镜、场景或资产时只生成相应记录，不附无关评测。
  video-server-order: "30"
  video-server-input-kinds: video
  video-server-output-contract: structured-report
  video-server-modules: drama-shot-craft, zh-copywriting-guidelines
---

# Plan

根据用途选择镜头拆解、场景整理或资产目录。默认整理叙事片段；镜头边界按真实剪切与画面变化判断，长镜头的信息变化不伪装成剪切。场景按时空与行动变化组织；资产按可辨认的身份整理。先覆盖全片，再复看不确定的边界或身份。

# Draft

只提交选中的记录。镜头记录按时间排列，写清景别、动作、镜头动机和起止；场景记录说明地点、行动及前后变化；资产目录合并重复出现的同一候选，并说明可见状态和位置。利用 sections 分组、items 列记录，evidence 绑定原位置；不凑高光、优缺点、建议和总结。不能完整识别时明确具体范围，不猜品牌或人物身份。

# Review

核对时间顺序、边界、重复记录和身份归并。区分连续拍摄与剪切、同一资产与相似物品；不能由图像确认的字段保持未知。整理是否服务用户用途是首要标准，不要求所有字段都长篇解释。

def video_report_labels(language: str) -> dict[str, str]:
    if language.lower().startswith("zh"):
        return {
            "deck": "以画面为证据，梳理全片的内容推进、镜头选择与后续制作重点。",
            "takeaway": "核心判断",
            "duration": "片长",
            "segments": "分析分镜",
            "scene_count": "内容段落",
            "highlight_count": "高光候选",
            "story_flow": "内容如何展开",
            "story_flow_intro": ("按时间顺序，全片可以分为以下几个段落。"),
            "location": "空间",
            "scene_role": "段落作用",
            "visual_rules": "应保持的画面规则",
            "watch_out": "连续性风险",
            "shot_breakdown": "逐镜证据",
            "shot_breakdown_intro": (
                "下表保留完整时码与边界类型，供导演、剪辑和生成团队逐项回看。"
            ),
            "shot_number": "分镜",
            "timecode": "时间码",
            "shot_duration": "时长",
            "picture_content": "画面内容",
            "camera_language": "景别 / 运镜 / 边界",
            "narrative": "镜头作用",
            "highlight_level": "重要度",
            "highlights": "值得回看的片段",
            "no_highlights": (
                "当前证据中没有足够独立的高光候选；报告不为了凑数放大普通片段。"
            ),
            "highlight_why": "保留理由",
            "highlight_range": "回看区间",
            "relative_score": "片内相对分值",
            "production_advice": "修改建议",
            "priority_shots": "优先回看的分镜",
            "assets": "需保持一致的视觉资产",
            "no_assets": ("当前画面没有形成可稳定复用的视觉资产，暂不建立空泛目录。"),
            "asset_type": "类别",
            "first_seen": "首次出现",
            "method": "分析口径与局限",
            "method_note": (
                "报告以可见画面为证据，区分真实编辑边界与连续长镜头内的视觉节拍；"
                "时间线连续覆盖全片，但不按固定秒数切片。对白、音乐、人物真实身份"
                "和平台效果不在没有可靠证据时推断。"
            ),
            "shot_ref": "分镜",
            "colon": "：",
            "list_separator": "、",
        }
    return {
        "deck": (
            "An evidence-led editorial reading of how the video develops, where its "
            "strongest moments land, and what production should protect next."
        ),
        "takeaway": "Key findings",
        "duration": "Duration",
        "segments": "Analysis segments",
        "scene_count": "Story sections",
        "highlight_count": "Highlight candidates",
        "story_flow": "How the video unfolds",
        "story_flow_intro": (
            "Before the technical breakdown, follow the visible progression across "
            "the timeline."
        ),
        "location": "Setting",
        "scene_role": "Role in the video",
        "visual_rules": "Visual rules worth preserving",
        "watch_out": "Continuity risks",
        "shot_breakdown": "Segment-by-segment evidence",
        "shot_breakdown_intro": (
            "The complete timecode and boundary record remains below for review by "
            "directors, editors, and generation teams."
        ),
        "shot_number": "Segment",
        "timecode": "Timecode",
        "shot_duration": "Duration",
        "picture_content": "What is visible",
        "camera_language": "Framing / motion / boundary",
        "narrative": "Why it is here",
        "highlight_level": "Importance",
        "highlights": "Moments worth revisiting",
        "no_highlights": (
            "The available evidence does not support a distinct highlight candidate; "
            "ordinary footage is not promoted merely to fill the section."
        ),
        "highlight_why": "Why it holds up",
        "highlight_range": "Review range",
        "relative_score": "Relative score within this video",
        "production_advice": "Recommended revisions",
        "priority_shots": "Priority segments",
        "assets": "Visual assets production should keep consistent",
        "no_assets": (
            "No stable reusable visual asset is supported by the current evidence."
        ),
        "asset_type": "Type",
        "first_seen": "First seen",
        "method": "Method and limits",
        "method_note": (
            "This report uses visible evidence, distinguishes physical edits from "
            "meaningful beats inside continuous takes, and covers the full timeline "
            "without fixed-interval slicing. It does not infer audio, identity, or "
            "platform outcomes without reliable evidence."
        ),
        "shot_ref": "Segment",
        "colon": ": ",
        "list_separator": ", ",
    }

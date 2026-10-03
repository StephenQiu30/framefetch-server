"""Select stage context from the immutable method snapshot, never live files."""

import re


def content_method(snapshot: str, *, review: bool) -> str:
    markers = list(
        re.finditer(
            r"^# (Source module: [a-z0-9-]+|Draft|Review)\s*$", snapshot, re.MULTILINE
        )
    )
    selected: list[str] = []
    for index, marker in enumerate(markers):
        label = marker.group(1)
        end = markers[index + 1].start() if index + 1 < len(markers) else len(snapshot)
        if (
            label == ("Review" if review else "Draft")
            or label == "Source module: zh-copywriting-guidelines"
            or label
            == (
                "Source module: humanizer-zh"
                if review
                else "Source module: baoyu-article-title"
            )
        ):
            selected.append(snapshot[marker.start() : end].strip())
    if not any(
        marker.group(1) == ("Review" if review else "Draft") for marker in markers
    ):
        raise ValueError("content method is missing its stage")
    return "\n\n".join(selected)

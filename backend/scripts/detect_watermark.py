"""Conservative, local recognition of branded corner overlays.

OCR text alone is not evidence that a region is a watermark. Only recognized
brand signatures near the frame edge are eligible; ordinary subtitles and
unknown graphical marks are left intact. This deliberately favors precision.
"""

from __future__ import annotations

import hashlib
import re
from importlib.metadata import version
from pathlib import Path

MODEL_HASHES = {
    "ch_PP-OCRv4_det_infer.onnx": (
        "d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9"
    ),
    "ch_PP-OCRv4_rec_infer.onnx": (
        "48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b"
    ),
    "ch_ppocr_mobile_v2.0_cls_infer.onnx": (
        "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"
    ),
}
SIGNATURE = re.compile(
    r"b[il1]*b[il1]+|哔哩哔哩|抖音(?:号)?|douyin|tiktok|快手|kuaishou|"
    r"小红书|xiaohongshu|微博|weibo|西瓜视频|好看视频|秒拍|美拍|"
    r"ttcount(?:er|en)|youtube|优酷|youku|腾讯视频|爱奇艺|iqiyi|"
    r"gettyimages|shutterstock|视觉中国|快影|剪映|capcut|秒剪",
    re.I,
)


def is_signature(text: str) -> bool:
    return bool(SIGNATURE.fullmatch(re.sub(r"[\s._·：:]", "", text)))


class Detector:
    def __init__(self, root: Path):
        from rapidocr import RapidOCR

        if version("rapidocr") != "3.4.2":
            raise ValueError("unexpected OCR runtime")
        for name, expected in MODEL_HASHES.items():
            with (root / name).open("rb") as file:
                if hashlib.file_digest(file, "sha256").hexdigest() != expected:
                    raise ValueError("OCR model checksum mismatch")
        self.engine = RapidOCR(
            params={
                "Det.model_path": str(root / "ch_PP-OCRv4_det_infer.onnx"),
                "Rec.model_path": str(root / "ch_PP-OCRv4_rec_infer.onnx"),
                "Cls.model_path": str(root / "ch_ppocr_mobile_v2.0_cls_infer.onnx"),
                "Global.font_path": str(root / "FZYTK.TTF"),
                "Global.log_level": "warning",
                "EngineConfig.onnxruntime.intra_op_num_threads": 4,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            }
        )

    def boxes(self, image):
        import cv2

        height, width = image.shape[:2]
        boxes = []
        # Padding makes text touching the image boundary detectable.
        for ox, oy, ex, ey in (
            (0, 0, width // 2, round(height * 0.28)),
            (width // 2, 0, width, round(height * 0.28)),
            (0, round(height * 0.72), width // 2, height),
            (width // 2, round(height * 0.72), width, height),
        ):
            crop = cv2.copyMakeBorder(
                image[oy:ey, ox:ex],
                32,
                32,
                32,
                32,
                cv2.BORDER_CONSTANT,
                value=(128, 128, 128),
            )
            result = self.engine(crop)
            if result.boxes is None:
                continue
            candidates = []
            for points, text, score in zip(
                result.boxes, result.txts, result.scores, strict=True
            ):
                x1, y1 = points.min(axis=0)
                x2, y2 = points.max(axis=0)
                box = [
                    max(0, round(x1) + ox - 32),
                    max(0, round(y1) + oy - 32),
                    min(width, round(x2) + ox - 32),
                    min(height, round(y2) + oy - 32),
                ]
                candidates.append((box, text, score))
            for anchor, text, score in candidates:
                if score < 0.7 or not is_signature(text):
                    continue
                x1, y1, x2, y2 = anchor
                # Require a corner position, not merely text mentioning a site.
                if not (
                    (y2 <= height * 0.18 or y1 >= height * 0.82)
                    and (x1 <= width * 0.2 or x2 >= width * 0.8)
                ):
                    continue
                box = list(anchor)
                # Creator name on the same line is part of a platform corner mark.
                for other, _, confidence in candidates:
                    if confidence < 0.8 or other == anchor:
                        continue
                    overlap = min(y2, other[3]) - max(y1, other[1])
                    gap = max(other[0] - x2, x1 - other[2], 0)
                    if (
                        overlap >= min(y2 - y1, other[3] - other[1]) * 0.6
                        and gap <= (y2 - y1) * 0.6
                    ):
                        box = [
                            min(box[0], other[0]),
                            min(box[1], other[1]),
                            max(box[2], other[2]),
                            max(box[3], other[3]),
                        ]
                pad = max(4, round(height * 0.006))
                box = (
                    max(0, box[0] - pad),
                    max(0, box[1] - pad),
                    min(width, box[2] + pad),
                    min(height, box[3] + pad),
                )
                if (box[2] - box[0]) * (box[3] - box[1]) > width * height * 0.12:
                    continue
                if min(anchor[2] - anchor[0], anchor[3] - anchor[1]) < 3:
                    continue
                template = cv2.Canny(image[y1:y2, x1:x2], 80, 160)
                if cv2.countNonZero(template) < 20:
                    continue
                boxes.append((box, tuple(anchor), template))
        return boxes


def scan(source: Path, detector: Detector):
    import av

    samples = []
    next_at = 0.0
    with av.open(str(source)) as video:
        for frame in video.decode(video=0):
            at = float(frame.pts * frame.time_base)
            if at + 0.00001 < next_at:
                continue
            boxes = detector.boxes(frame.to_ndarray(format="bgr24"))
            samples.append((at, boxes))
            next_at = at + 0.5
    return samples


def matching_boxes(image, at: float, samples):
    import cv2
    import numpy as np

    matched = []
    for moment, boxes in samples:
        if abs(moment - at) > 0.5:
            continue
        for box, anchor, template in boxes:
            x1, y1, x2, y2 = anchor
            edges = cv2.Canny(image[y1:y2, x1:x2], 80, 160)
            dilated = cv2.dilate(edges, np.ones((3, 3), np.uint8))
            agreement = cv2.countNonZero(
                cv2.bitwise_and(template, dilated)
            ) / cv2.countNonZero(template)
            if agreement < 0.72:
                continue
            if any(intersection_over_union(box, other) > 0.5 for other in matched):
                continue
            matched.append(box)
    return tuple(sorted(matched))


def intersection_over_union(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0

"""Bounded previews from actual extracted frames, preserved with the revision."""

import base64
import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image


def frame_preview(path: Path) -> dict[str, object]:
    original = path.read_bytes()
    with Image.open(BytesIO(original)) as image:
        if image.format != "PNG":
            raise ValueError("actual PNG frame required")
        preview = image.convert("RGB")
        for width in (256, 192, 128, 64):
            preview.thumbnail((width, width))
            output = BytesIO()
            preview.save(output, format="PNG", optimize=True)
            encoded = output.getvalue()
            if len(encoded) <= 48_000:
                return {
                    "frame_sha256": hashlib.sha256(original).hexdigest(),
                    "preview_sha256": hashlib.sha256(encoded).hexdigest(),
                    "preview_media_type": "image/png",
                    "preview_data_base64": base64.b64encode(encoded).decode(),
                    "preview_width": preview.width,
                    "preview_height": preview.height,
                }
    raise ValueError("frame preview exceeds the bounded resource limit")

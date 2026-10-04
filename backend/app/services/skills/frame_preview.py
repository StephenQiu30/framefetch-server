"""Bounded previews from actual extracted frames for an immutable analysis input."""

import base64
import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image


def frame_preview(path: Path) -> dict[str, object]:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 10 * 1024 * 1024
    ):
        raise ValueError("actual frame exceeds the bounded resource limit")
    original = path.read_bytes()
    with Image.open(BytesIO(original)) as image:
        if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
            raise ValueError("actual PNG frame required")
        if image.width * image.height > 4096 * 2160:
            raise ValueError("actual frame pixel limit exceeded")
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

"""Native pinned baoyu renderer, no model inference or network permissions."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import tempfile
from pathlib import Path

from app.services.analysis.skills.upstream_catalog import UpstreamCatalog


async def render_wechat_html(markdown: str) -> bytes:
    UpstreamCatalog().verify("baoyu")
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("native Markdown renderer unavailable")
    script = Path(__file__).with_suffix(".mjs")
    with tempfile.TemporaryDirectory(prefix="framefetch-html-") as directory:
        # Do not read the host user's optional EXTEND configuration.
        process = await asyncio.create_subprocess_exec(
            node,
            str(script),
            cwd=directory,
            env={"PATH": os.defpath, "HOME": directory, "XDG_CONFIG_HOME": directory},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            async with asyncio.timeout(60):
                output, _ = await process.communicate(markdown.encode("utf-8"))
            if process.returncode != 0 or not 0 < len(output) <= 16 * 1024**2:
                raise RuntimeError("native Markdown rendering failed")
            return output
        finally:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()

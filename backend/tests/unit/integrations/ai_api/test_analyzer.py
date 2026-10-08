from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from app.integrations.ai_api.analyzer import ApiAnalyzer
from app.integrations.ai_api.config import ApiAdapterConfig
from app.integrations.ai_api.frames import FrameEvidence
from tests.unit.integrations.ai_cli.helpers import (
    request,
    screenplay_request,
    screenplay_synthesis_request,
)


class FakeInvoker:
    def __init__(self, owner: FakeModel) -> None:
        self.owner = owner

    async def ainvoke(self, value: object) -> object:
        self.owner.inputs.append(value)
        return {"controlled": True}


class FakeModel:
    def __init__(self) -> None:
        self.schemas: list[dict[str, Any]] = []
        self.inputs: list[object] = []

    def with_structured_output(
        self,
        schema: dict[str, Any],
        *,
        method: str,
        include_raw: bool,
    ) -> FakeInvoker:
        assert method == "json_mode"
        assert include_raw is False
        self.schemas.append(schema)
        return FakeInvoker(self)


class FakeFrames:
    async def extract(
        self,
        video: Path,
        *,
        workspace: Path,
        duration_ms: int,
        observation_ms: tuple[int, ...] = (),
    ) -> tuple[FrameEvidence, ...]:
        assert video == workspace / "input" / "video.bin"
        assert duration_ms == 2_000
        return (FrameEvidence(0, b"first"), FrameEvidence(1_000, b"second"))


def config() -> ApiAdapterConfig:
    executable = Path(sys.executable)
    return ApiAdapterConfig(
        model="deepseek-v4-flash-vision-exp",
        base_url="https://api.deepseek.com",
        ffmpeg=executable,
        ffprobe=executable,
        timeout_seconds=30,
        max_stdout_bytes=1024 * 1024,
        max_stderr_bytes=1024,
        max_workspace_bytes=10 * 1024 * 1024,
        max_workspace_files=32,
        max_frames=8,
        max_image_bytes=1024,
        workspace_poll_seconds=0.01,
        terminate_grace_seconds=1,
    )


@pytest.mark.asyncio
async def test_video_analysis_sends_ordered_inline_screenshots(tmp_path: Path) -> None:
    model = FakeModel()
    analyzer = ApiAnalyzer(
        config(),
        model=model,
        frames=FakeFrames(),  # type: ignore[arg-type]
    )

    result = await analyzer.analyze(request(tmp_path))

    assert result == {"controlled": True}
    messages = model.inputs[0]
    content = messages[0].content  # type: ignore[index,union-attr]
    assert content[1]["text"] == "截图 1 · 0 ms（按时间顺序）"
    assert content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert content[3]["text"] == "截图 2 · 1000 ms（按时间顺序）"
    assert "不得调用工具" in content[0]["text"]
    assert "JSON Schema" in content[0]["text"]


@pytest.mark.asyncio
async def test_screenplay_operations_share_structured_langchain_client(
    tmp_path: Path,
) -> None:
    model = FakeModel()
    analyzer = ApiAnalyzer(config(), model=model)

    assert await analyzer.analyze_screenplay(screenplay_request(tmp_path))
    assert await analyzer.synthesize_screenplay_analysis(
        screenplay_synthesis_request(tmp_path)
    )
    assert len(model.schemas) == 2
    assert all("JSON Schema" in call[0].content[0]["text"] for call in model.inputs)  # type: ignore[index,union-attr]

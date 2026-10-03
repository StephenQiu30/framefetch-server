"""OpenAI-compatible chat transport, with explicit OpenRouter routing policy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.messages import HumanMessage

from app.integrations.ai_api.http import request_json
from app.integrations.ai_cli.errors import AnalysisCliError
from app.services.ai_model_catalog import AiModelCatalog, ModelCatalogUnavailable


class ChatCompletionsModel:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float,
        maximum_bytes: int,
        catalog: AiModelCatalog | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._maximum = maximum_bytes
        self._catalog = catalog
        self._transport = transport

    def with_structured_output(
        self,
        schema: dict[str, Any],
        *,
        method: str,
        include_raw: bool,
    ) -> _ChatInvoker:
        if method != "json_mode" or include_raw:
            raise AnalysisCliError("analysis_cli_unsupported")
        return _ChatInvoker(self, schema)

    async def complete(self, content: object, schema: dict[str, Any]) -> object:
        response_format: dict[str, Any] = {"type": "json_object"}
        body: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "messages": [{"role": "user", "content": content}],
        }
        if self._catalog is not None:
            images = isinstance(content, list) and any(
                isinstance(part, dict) and part.get("type") == "image_url"
                for part in content
            )
            try:
                models = await self._catalog.list_models()
            except ModelCatalogUnavailable:
                raise AnalysisCliError("analysis_cli_unavailable") from None
            selected = next(
                (model for model in models if model.id == self._model), None
            )
            if selected is None or not selected.supports_analysis(images=images):
                raise AnalysisCliError("analysis_cli_unsupported")
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "framefetch_analysis",
                    "strict": True,
                    "schema": schema,
                },
            }
            body["provider"] = {"require_parameters": True, "allow_fallbacks": False}
        body["response_format"] = response_format
        response = await request_json(
            "POST",
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            body=body,
            timeout_seconds=self._timeout,
            maximum_bytes=self._maximum,
            transport=self._transport,
        )
        try:
            choice = response["choices"][0]
            if not isinstance(choice, dict):
                raise AnalysisCliError("invalid_model_output", outcome_known=True)
            message = choice["message"]
            if not isinstance(message, dict):
                raise AnalysisCliError("invalid_model_output", outcome_known=True)
            if choice.get("finish_reason") != "stop" or message.get("refusal"):
                raise AnalysisCliError("invalid_model_output", outcome_known=True)
            result = json.loads(message["content"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise AnalysisCliError("invalid_model_output", outcome_known=True) from None
        if not isinstance(result, dict):
            raise AnalysisCliError("invalid_model_output", outcome_known=True)
        return result


@dataclass(frozen=True)
class _ChatInvoker:
    model: ChatCompletionsModel
    schema: dict[str, Any]

    async def ainvoke(self, value: object) -> object:
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], HumanMessage)
        ):
            raise AnalysisCliError("invalid_model_output", outcome_known=True)
        return await self.model.complete(value[0].content, self.schema)

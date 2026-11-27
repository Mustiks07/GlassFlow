"""Test doubles (tests only). These are scripted providers, never used by release code."""

from __future__ import annotations

import json
from collections.abc import Callable

from glassflow.modules.intelligence.providers.base import (
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
    Usage,
)


def tool_call(name: str, args: dict | str, call_id: str | None = None) -> ToolCall:
    raw = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
    parsed = None if isinstance(args, str) else args
    return ToolCall(call_id or f"c-{name}", name, raw, parsed)


def reply(*calls: ToolCall, text: str | None = None, model: str = "scripted-model") -> ProviderResponse:
    return ProviderResponse(
        provider="scripted",
        model_id=model,
        text=text,
        tool_calls=list(calls),
        usage=Usage(input_tokens=100, output_tokens=20, cost_usd=None, cost_source="not_reported"),
    )


class ScriptedProvider:
    """Returns scripted responses / raises scripted errors in order; records requests."""

    name = "scripted"

    def __init__(self, script: list[ProviderResponse | ProviderError | Callable[[ProviderRequest], ProviderResponse]], model_id="scripted-model"):
        self.script = list(script)
        self.model_id = model_id
        self.requests: list[ProviderRequest] = []

    def capabilities(self) -> dict[str, bool]:
        return {"tools": True, "structured_output": False, "thought_signatures": False, "usage": True}

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        if not self.script:
            raise ProviderError("server", "script exhausted")
        item = self.script.pop(0)
        if isinstance(item, ProviderError):
            raise item
        if callable(item):
            return item(request)
        return item

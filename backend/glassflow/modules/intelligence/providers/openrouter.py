"""OpenRouter adapter: OpenAI-compatible chat completions over HTTPS (httpx).

Only a concrete, pre-verified model id is used; ``openrouter/free``/``auto`` routers are
rejected by policy. Provider fallbacks inside OpenRouter are disabled so the recorded model
is the model that answered. Usage cost is requested (``usage.include``) and recorded when the
API returns it; otherwise it stays unknown.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from .base import ChatMessage, ProviderError, ProviderRequest, ProviderResponse, ToolCall, Usage, sanitize

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, model_id: str, api_key: str, *, base_url: str = API_URL, transport: Any | None = None):
        self.model_id = model_id
        self._api_key = api_key
        self._url = base_url
        self._transport = transport

    def capabilities(self) -> dict[str, bool]:
        return {"tools": True, "structured_output": False, "thought_signatures": False, "usage": True}

    @staticmethod
    def _messages(system: str, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for message in messages:
            if message.role == "tool":
                out.append({"role": "tool", "tool_call_id": message.tool_call_id, "content": message.text or ""})
            elif message.role == "assistant":
                item: dict[str, Any] = {"role": "assistant", "content": message.text or ""}
                if message.tool_calls:
                    item["tool_calls"] = [
                        {"id": call.call_id, "type": "function", "function": {"name": call.name, "arguments": call.arguments_json}}
                        for call in message.tool_calls
                    ]
                out.append(item)
            else:
                out.append({"role": "user", "content": message.text or ""})
        return out

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        import httpx

        body: dict[str, Any] = {
            "model": self.model_id,
            "messages": self._messages(request.system, request.messages),
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "usage": {"include": True},
            "provider": {"allow_fallbacks": False},
        }
        if request.tools:
            body["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in request.tools
            ]
            body["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self._api_key}", "X-Title": "GlassFlow"}
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=request.timeout_s, transport=self._transport) as client:
                reply = await client.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException:
            raise ProviderError("timeout", "OpenRouter: тайм-аут.", provider=self.name, model_id=self.model_id) from None
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"OpenRouter: сбой соединения ({type(exc).__name__}).", provider=self.name, model_id=self.model_id) from None
        latency = int((time.monotonic() - started) * 1000)
        try:
            payload = reply.json()
        except ValueError:
            payload = {}
        error = payload.get("error") if isinstance(payload, dict) else None
        status = reply.status_code
        if status >= 400 or error:
            code = status if status >= 400 else int((error or {}).get("code") or 500)
            message = sanitize(str((error or {}).get("message", "")), [self._api_key])
            retry_after = None
            try:
                retry_after = float(reply.headers.get("retry-after")) if reply.headers.get("retry-after") else None
            except ValueError:
                retry_after = None
            kind = {401: "auth", 403: "auth", 402: "budget", 429: "rate_limit", 408: "timeout"}.get(code)
            if kind is None:
                kind = "server" if code >= 500 else "bad_request"
            raise ProviderError(kind, f"OpenRouter {code}: {message}", status=code, retry_after_s=retry_after, provider=self.name, model_id=self.model_id)
        try:
            choice = payload["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("malformed", "OpenRouter: ответ без choices.", provider=self.name, model_id=self.model_id) from None
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            raw = function.get("arguments") or "{}"
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(parsed, dict):
                    parsed = None
            except json.JSONDecodeError:
                parsed = None
            calls.append(
                ToolCall(call_id=call.get("id") or "", name=function.get("name") or "", arguments_json=raw if isinstance(raw, str) else json.dumps(raw), arguments=parsed)
            )
        usage_raw = payload.get("usage") or {}
        cost = None
        if usage_raw.get("cost") is not None:
            try:
                cost = Decimal(str(usage_raw["cost"]))
            except InvalidOperation:
                cost = None
        usage = Usage(
            input_tokens=usage_raw.get("prompt_tokens"),
            output_tokens=usage_raw.get("completion_tokens"),
            thought_tokens=(usage_raw.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            cached_tokens=(usage_raw.get("prompt_tokens_details") or {}).get("cached_tokens"),
            cost_usd=cost,
            cost_source="openrouter_usage_cost_usd" if cost is not None else "not_reported",
        )
        return ProviderResponse(
            provider=self.name,
            model_id=payload.get("model") or self.model_id,
            text=message.get("content") or None,
            tool_calls=calls,
            usage=usage,
            finish_reason=choice.get("finish_reason"),
            latency_ms=latency,
            request_id=payload.get("id"),
        )

"""Client side of the ``judge_gateway`` profile.

The local app sends only the conversation messages and the prompt version. The gateway owns
the system prompt, tool schemas, pinned model ids, budget and free_only policy; the provider
key never leaves the server. Tool calls returned by the gateway are executed and validated
locally like any other untrusted model output.
"""

from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from typing import Any

from .base import ChatMessage, ProviderError, ProviderRequest, ProviderResponse, ToolCall, Usage, sanitize

MAX_STATE_BYTES = 64_000


def message_to_wire(message: ChatMessage) -> dict[str, Any]:
    return {
        "role": message.role,
        "text": message.text,
        "tool_calls": [
            {"call_id": c.call_id, "name": c.name, "arguments_json": c.arguments_json} for c in message.tool_calls
        ],
        "tool_call_id": message.tool_call_id,
        "tool_name": message.tool_name,
        "provider_state": message.provider_state,
    }


def message_from_wire(data: dict[str, Any]) -> ChatMessage:
    return ChatMessage(
        role=data["role"],
        text=data.get("text"),
        tool_calls=[ToolCall(c["call_id"], c["name"], c.get("arguments_json") or "{}") for c in data.get("tool_calls") or []],
        tool_call_id=data.get("tool_call_id"),
        tool_name=data.get("tool_name"),
        provider_state=data.get("provider_state"),
    )


class GatewayProvider:
    name = "judge_gateway"

    def __init__(self, base_url: str, token: str, *, prompt_version: str, session_id: str, transport: Any | None = None):
        if not base_url.startswith("https://") and not base_url.startswith("http://127.0.0.1") and not base_url.startswith("http://localhost"):
            raise ValueError("judge_gateway требует HTTPS (http разрешен только для локальной проверки)")
        self.model_id = "gateway-pinned"
        self._url = base_url.rstrip("/") + "/v1/turn"
        self._token = token
        self._prompt_version = prompt_version
        self._session_id = session_id
        self._transport = transport

    def capabilities(self) -> dict[str, bool]:
        return {"tools": True, "structured_output": False, "thought_signatures": True, "usage": True}

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        import httpx

        body = {
            "session_id": self._session_id,
            "prompt_version": self._prompt_version,
            "purpose": request.purpose,
            "messages": [message_to_wire(m) for m in request.messages],
        }
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=request.timeout_s, transport=self._transport) as client:
                reply = await client.post(self._url, json=body, headers={"Authorization": f"Bearer {self._token}"})
        except httpx.TimeoutException:
            raise ProviderError("timeout", "Шлюз AI: тайм-аут.", provider=self.name) from None
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"Шлюз AI недоступен ({type(exc).__name__}).", provider=self.name) from None
        try:
            payload = reply.json()
        except ValueError:
            payload = {}
        if reply.status_code >= 400:
            code = reply.status_code
            message = sanitize(str(payload.get("message_ru") or payload.get("code") or ""), [self._token])
            kind = {401: "auth", 403: "auth", 402: "budget", 429: "rate_limit", 409: "policy", 413: "bad_request"}.get(code)
            if kind is None:
                kind = "server" if code >= 500 else "bad_request"
            retry_after = payload.get("retry_after_s")
            raise ProviderError(kind, f"Шлюз AI {code}: {message}", status=code, retry_after_s=retry_after, provider=self.name)
        try:
            usage_raw = payload.get("usage") or {}
            cost = usage_raw.get("cost_usd")
            try:
                cost_value = Decimal(str(cost)) if cost is not None else None
            except InvalidOperation:
                cost_value = None
            response = ProviderResponse(
                provider=f"{self.name}/{payload.get('provider', 'unknown')}",
                model_id=payload.get("model_id") or "unknown",
                text=payload.get("text"),
                tool_calls=[ToolCall(c["call_id"], c["name"], c.get("arguments_json") or "{}") for c in payload.get("tool_calls") or []],
                usage=Usage(
                    input_tokens=usage_raw.get("input_tokens"),
                    output_tokens=usage_raw.get("output_tokens"),
                    thought_tokens=usage_raw.get("thought_tokens"),
                    cached_tokens=usage_raw.get("cached_tokens"),
                    cost_usd=cost_value,
                    cost_source=usage_raw.get("cost_source") or "gateway",
                ),
                finish_reason=payload.get("finish_reason"),
                latency_ms=int((time.monotonic() - started) * 1000),
                provider_state=payload.get("provider_state"),
            )
        except (KeyError, TypeError) as exc:
            raise ProviderError("malformed", f"Шлюз AI: некорректный ответ ({type(exc).__name__}).", provider=self.name) from None
        return response

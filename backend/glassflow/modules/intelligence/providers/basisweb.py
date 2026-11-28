"""Explicit included-quota BasisWeb profile; no money/top-up or routing fallback.

Host and model rates are pinned to the supplier catalog checked by the integrator
on 2026-11-28. Quota accounting is conservative and independent of a delayed meter.
Credentials are memory-only and never included in diagnostics.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

from .base import ProviderError, ProviderRequest, ProviderResponse, ToolCall, Usage, sanitize
from .openrouter import OpenRouterProvider

API_URL = "https://api.basisweb.ru/v1/chat/completions"
# multiplier, input, output, cached-input weights. This is quota, not USD pricing.
QUOTA_RATES = {
    "gpt-6-luna": (1, 1, 5, 0.1),
    "glm-5.3-flash": (2, 1, 1, 1),
    "gpt-6.1-terra": (3, 1, 5, 0.05),
}


def reserve_quota(request: ProviderRequest, model: str) -> int:
    """UTF-8 byte upper estimate + protocol allowance; output reserved at full cap."""
    body = {"messages": OpenRouterProvider._messages(request.system, request.messages),
            "tools": [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in request.tools]}
    input_upper = len(json.dumps(body, ensure_ascii=False).encode("utf-8")) + 1024
    multiplier, input_rate, output_rate, _ = QUOTA_RATES[model]
    return math.ceil(multiplier * (input_upper * input_rate + request.max_output_tokens * output_rate))


def usage_quota(usage: Usage, model: str) -> int | None:
    if usage.input_tokens is None or usage.output_tokens is None:
        return None
    multiplier, input_rate, output_rate, cached_rate = QUOTA_RATES[model]
    cached = min(usage.input_tokens, usage.cached_tokens or 0)
    return math.ceil(multiplier * ((usage.input_tokens - cached) * input_rate + cached * cached_rate
                                   + usage.output_tokens * output_rate))


class BasisWebProvider:
    name = "basisweb"

    def __init__(self, model_id: str, api_key: str, *, base_url: str = API_URL, transport: Any | None = None):
        if base_url != API_URL:
            raise ValueError("BasisWeb разрешен только на проверенном HTTPS API host/path.")
        if model_id not in QUOTA_RATES:
            raise ValueError("Для модели BasisWeb отсутствует проверенный тариф включенной квоты.")
        self.model_id, self._api_key, self._transport = model_id, api_key, transport

    def capabilities(self) -> dict[str, bool]:
        return {"tools": True, "structured_output": False, "thought_signatures": False, "usage": True}

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        import httpx

        body: dict[str, Any] = {"model": self.model_id,
                                "messages": OpenRouterProvider._messages(request.system, request.messages),
                                "max_tokens": request.max_output_tokens, "temperature": request.temperature}
        if request.tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters}} for t in request.tools]
            body["tool_choice"] = "auto"
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=request.timeout_s, transport=self._transport, follow_redirects=False) as client:
                reply = await client.post(API_URL, json=body, headers={"Authorization": f"Bearer {self._api_key}"})
        except httpx.TimeoutException:
            raise ProviderError("timeout", "BasisWeb: тайм-аут.", provider=self.name, model_id=self.model_id) from None
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"BasisWeb: сбой соединения ({type(exc).__name__}).",
                                provider=self.name, model_id=self.model_id) from None
        try:
            payload = reply.json()
        except ValueError:
            payload = {}
        error = payload.get("error") if isinstance(payload, dict) else None
        if reply.status_code >= 300 or error:
            status = reply.status_code if reply.status_code >= 300 else 500
            kind = {401: "auth", 403: "auth", 402: "budget", 429: "rate_limit", 408: "timeout"}.get(status)
            kind = kind or ("server" if status >= 500 else "bad_request")
            message = sanitize(str(error)[:500], [self._api_key]) if error else "запрос отклонен"
            try:
                retry_after = float(reply.headers["retry-after"]) if "retry-after" in reply.headers else None
            except ValueError:
                retry_after = None
            raise ProviderError(kind, f"BasisWeb {status}: {message}", provider=self.name, model_id=self.model_id,
                                status=status, retry_after_s=retry_after)
        try:
            choice = payload["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict):
                raise TypeError
            actual_model = payload.get("model")
            if actual_model != self.model_id:
                raise ValueError("unexpected model")
            calls = []
            for call in message.get("tool_calls") or []:
                function = call["function"]
                raw = function.get("arguments") or "{}"
                try:
                    arguments = json.loads(raw) if isinstance(raw, str) else raw
                except ValueError:
                    arguments = None
                calls.append(ToolCall(call.get("id") or "", function.get("name") or "",
                                      raw if isinstance(raw, str) else json.dumps(raw),
                                      arguments if isinstance(arguments, dict) else None))
            raw_usage = payload.get("usage") or {}
            def token(name, details=None):
                value = (raw_usage.get(details) or {}).get(name) if details else raw_usage.get(name)
                return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
            usage = Usage(input_tokens=token("prompt_tokens"), output_tokens=token("completion_tokens"),
                          cached_tokens=token("cached_tokens", "prompt_tokens_details"),
                          thought_tokens=token("reasoning_tokens", "completion_tokens_details"),
                          cost_source="basisweb_included_quota_usage_no_usd_price")
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("malformed", "BasisWeb: некорректный ответ или подмена выбранной модели.",
                                provider=self.name, model_id=self.model_id) from None
        return ProviderResponse(provider=self.name, model_id=actual_model, text=message.get("content") or None,
                                tool_calls=calls, usage=usage, finish_reason=choice.get("finish_reason"),
                                latency_ms=int((time.monotonic() - started) * 1000), request_id=payload.get("id"))

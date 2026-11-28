"""judge_gateway: a small FastAPI service that proxies only the assistant's model calls.

Server-pinned: provider, model ids, system prompt, tool schemas, output-token ceiling,
free_only policy and budgets. The client sends only conversation messages (user text, model
turns it received earlier, results of tools it executed locally) and the prompt version.
The gateway has no database, no CRM data and no tools of its own; returned tool calls are
validated and executed by the local application.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from glassflow.modules.intelligence.assistant.llm import tool_specs
from glassflow.modules.intelligence.assistant.prompts import SYSTEM_PROMPT
from glassflow.modules.intelligence.providers.base import AIProvider, ProviderError, ProviderRequest
from glassflow.modules.intelligence.providers.gateway_client import MAX_STATE_BYTES, message_from_wire
from glassflow.modules.intelligence.providers.policy import (
    AIProfile,
    MemoryLedger,
    ModelRef,
    ResilientClient,
    validate_profile,
)

from .config import GatewayConfig
from .tokens import verify

log = logging.getLogger("judge_gateway")


class WireToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: str = Field(max_length=128)
    name: str = Field(max_length=64)
    arguments_json: str = Field(max_length=8000)


class WireMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant", "tool"]
    text: str | None = Field(default=None, max_length=12000)
    tool_calls: list[WireToolCall] = Field(default_factory=list, max_length=8)
    tool_call_id: str | None = Field(default=None, max_length=128)
    tool_name: str | None = Field(default=None, max_length=64)
    provider_state: dict[str, Any] | None = None


class TurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=64)
    prompt_version: str = Field(max_length=64)
    purpose: Literal["assistant_turn", "assistant_tool_followup", "settings_check"] = "assistant_turn"
    tool_profile: Literal["default", "no_inventory"] = "default"
    messages: list[WireMessage] = Field(min_length=1)


def _error(status: int, code: str, message_ru: str, retry_after: float | None = None) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message_ru": message_ru}
    headers = {}
    if retry_after is not None:
        body["retry_after_s"] = round(retry_after, 1)
        headers["Retry-After"] = str(int(retry_after) + 1)
    return JSONResponse(status_code=status, content=body, headers=headers)


class _Window:
    def __init__(self) -> None:
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.totals: dict[str, int] = defaultdict(int)

    def hit(self, key: str, limit: int, now: float, window: float = 60.0) -> float | None:
        queue = self.events[key]
        while queue and now - queue[0] >= window:
            queue.popleft()
        if len(queue) >= limit:
            return window - (now - queue[0])
        queue.append(now)
        self.totals[key] += 1
        return None


def create_app(
    config: GatewayConfig | None = None,
    *,
    providers: dict[str, AIProvider] | None = None,
    secret_lookup=None,
) -> FastAPI:
    import os

    config = config or GatewayConfig.from_env()
    secret_lookup = secret_lookup or (lambda name: os.environ.get(name))
    profile = AIProfile(
        name="judge_gateway",
        mode=config.mode,  # type: ignore[arg-type]
        primary=ModelRef(provider=config.provider, model_id=config.models[0]) if config.models else None,  # type: ignore[arg-type]
        fallbacks=[ModelRef(provider=config.provider, model_id=m) for m in config.models[1:]],  # type: ignore[arg-type]
        budget_usd=config.limits.global_spend_usd if config.mode == "paid_enabled" else Decimal("0"),
        rpm=None,
        tpm=None,
        rpd=config.limits.global_requests_per_day,
        max_concurrency=config.limits.max_concurrency,
        turn_deadline_s=config.limits.request_deadline_s,
        max_tool_iterations=config.limits.max_tool_iterations,
    )
    policy_errors = validate_profile(profile)
    if providers is None:
        providers = {}
        key = secret_lookup(config.provider_key_env)
        if key and not policy_errors:
            from glassflow.modules.intelligence.providers.gemini import GeminiProvider
            from glassflow.modules.intelligence.providers.openrouter import OpenRouterProvider

            for ref in [profile.primary, *profile.fallbacks]:
                if ref is None:
                    continue
                cls = GeminiProvider if ref.provider == "gemini" else OpenRouterProvider
                providers[ref.label] = cls(ref.model_id, key)
    ledger = MemoryLedger()
    client = ResilientClient(profile=profile, providers=providers, ledger=ledger, prompt_version=config.prompt_version)
    windows = _Window()
    state = {"day": datetime.now(UTC).date(), "requests_today": 0, "spent": Decimal("0")}
    from glassflow.modules.intelligence.assistant.tools import ASSISTANT_TOOLSET

    tool_profiles = {
        "default": tool_specs(),
        "no_inventory": tool_specs([name for name in ASSISTANT_TOOLSET if name != "find_remnants"]),
    }

    app = FastAPI(title="GlassFlow judge_gateway", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ledger = ledger
    app.state.config = config

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        ready = not policy_errors and bool(client.chain()) and bool(config.tokens)
        body = {
            "status": "ready" if ready else "not_ready",
            "mode": config.mode,
            "models": config.models,
            "prompt_version": config.prompt_version,
            "provider_key_configured": bool(client.chain()),
            "active_tokens": sum(1 for t in config.tokens if not t.revoked),
            "policy_errors": policy_errors,
        }
        return JSONResponse(status_code=200 if ready else 503, content=body)

    @app.post("/v1/turn")
    async def turn(request: Request):
        started = time.monotonic()
        raw = await request.body()
        if len(raw) > config.limits.max_body_bytes:
            return _error(413, "BODY_TOO_LARGE", "Слишком большой запрос.")
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else ""
        record, reason = verify(token, config.tokens) if token else (None, "token_missing")
        if record is None:
            return _error(401, reason.upper(), "Конкурсный токен недействителен, просрочен или отозван.")
        try:
            body = TurnBody.model_validate_json(raw)
        except ValidationError:
            return _error(422, "INVALID_BODY", "Некорректный формат запроса.")
        if body.prompt_version != config.prompt_version:
            return _error(409, "PROMPT_VERSION_MISMATCH", f"Шлюз обслуживает версию {config.prompt_version}.")
        chars = sum(len(m.text or "") + sum(len(c.arguments_json) for c in m.tool_calls) for m in body.messages)
        if len(body.messages) > config.limits.max_messages or chars > config.limits.max_context_chars:
            return _error(413, "CONTEXT_TOO_LARGE", "Контекст превышает лимит шлюза.")
        if any(m.provider_state and len(str(m.provider_state)) > MAX_STATE_BYTES for m in body.messages):
            return _error(413, "STATE_TOO_LARGE", "Служебное состояние модели слишком велико.")
        rounds = sum(1 for m in body.messages if m.role == "assistant")
        if rounds >= config.limits.max_tool_iterations:
            return _error(409, "TOOL_ITERATION_CAP", "Достигнут предел шагов инструментов для одного хода.")
        now_day = datetime.now(UTC).date()
        if state["day"] != now_day:
            state["day"], state["requests_today"] = now_day, 0
        if state["requests_today"] >= config.limits.global_requests_per_day:
            return _error(429, "GLOBAL_DAILY_CAP", "Дневной лимит шлюза исчерпан.", 3600)
        if config.mode == "paid_enabled" and state["spent"] >= config.limits.global_spend_usd:
            return _error(402, "GLOBAL_SPEND_CAP", "Бюджет шлюза исчерпан.")
        host = request.client.host if request.client else "unknown"
        if config.trust_forwarded_for and request.headers.get("x-forwarded-for"):
            host = request.headers["x-forwarded-for"].split(",")[0].strip()
        now = time.monotonic()
        session_key = f"{record.token_id}:{body.session_id}"
        for key, limit in (
            (f"tok:{record.token_id}", config.limits.per_token_rpm),
            (f"ses:{session_key}", config.limits.per_session_rpm),
            (f"ip:{host}", config.limits.per_ip_rpm),
        ):
            wait = windows.hit(key, limit, now)
            if wait is not None:
                return _error(429, "RATE_LIMITED", "Слишком много запросов; повторите позже.", wait)
        if windows.totals[f"tok:{record.token_id}"] > record.max_requests:
            return _error(429, "TOKEN_QUOTA", "Квота конкурсного токена исчерпана.")
        if windows.totals[f"ses:{session_key}"] > config.limits.per_session_requests:
            return _error(429, "SESSION_QUOTA", "Квота сессии исчерпана.")
        if policy_errors:
            return _error(409, "POLICY_BLOCKED", policy_errors[0])
        if not client.chain():
            return _error(503, "PROVIDER_NOT_CONFIGURED", "Ключ провайдера на шлюзе не настроен.")
        state["requests_today"] += 1
        messages = [message_from_wire(m.model_dump()) for m in body.messages]
        provider_request = ProviderRequest(
            system=SYSTEM_PROMPT, messages=messages, tools=tool_profiles[body.tool_profile],
            max_output_tokens=profile.max_output_tokens, purpose=body.purpose
        )
        try:
            outcome = await client.call(provider_request, deadline=time.monotonic() + config.limits.request_deadline_s)
        except ProviderError as exc:
            status = {"auth": 502, "rate_limit": 429, "budget": 402, "policy": 409, "timeout": 504}.get(exc.kind, 502)
            _log(record.token_id, body.session_id, host, status, started, chars, exc.kind)
            return _error(status, f"PROVIDER_{exc.kind.upper()}", "Провайдер AI недоступен или ограничил запрос.", exc.retry_after_s)
        response = outcome.response
        if response.usage.cost_usd is not None:
            state["spent"] += response.usage.cost_usd
        _log(record.token_id, body.session_id, host, 200, started, chars, None)
        return {
            "provider": response.provider,
            "model_id": response.model_id,
            "text": response.text,
            "tool_calls": [{"call_id": c.call_id, "name": c.name, "arguments_json": c.arguments_json} for c in response.tool_calls],
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "thought_tokens": response.usage.thought_tokens,
                "cached_tokens": response.usage.cached_tokens,
                "cost_usd": f"{response.usage.cost_usd:f}" if response.usage.cost_usd is not None else None,
                "cost_source": response.usage.cost_source,
            },
            "finish_reason": response.finish_reason,
            "provider_state": response.provider_state,
            "attempts": outcome.attempts,
            "fallback_used": outcome.fallback_used,
        }

    return app


def _mask(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _log(token_id: str, session_id: str, host: str, status: int, started: float, chars: int, error: str | None) -> None:
    """Masked access log: no message text, no token, hashed session and client address."""
    log.info(
        "turn token=%s session=%s ip=%s status=%s ms=%d chars=%d error=%s",
        token_id, _mask(session_id), _mask(host), status, int((time.monotonic() - started) * 1000), chars, error or "-",
    )

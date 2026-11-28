"""Provider-neutral AI interface. Application logic depends on AIProvider, not on an SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments_json: str
    arguments: dict[str, Any] | None = None


@dataclass
class ChatMessage:
    role: str  # user | assistant | tool
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    provider_state: dict[str, Any] | None = None  # opaque, e.g. Gemini parts with thought signatures


@dataclass
class ProviderRequest:
    system: str
    messages: list[ChatMessage]
    tools: list[ToolSpec] = field(default_factory=list)
    max_output_tokens: int = 1024
    temperature: float = 0.1
    timeout_s: float = 20.0
    purpose: str = "assistant_turn"


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    thought_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: Decimal | None = None  # None means unknown, never an invented zero
    cost_source: str = "unknown"


@dataclass
class ProviderResponse:
    provider: str
    model_id: str
    text: str | None
    tool_calls: list[ToolCall]
    usage: Usage
    finish_reason: str | None = None
    latency_ms: int | None = None
    provider_state: dict[str, Any] | None = None
    request_id: str | None = None


ERROR_KINDS = {
    "auth",  # 401/403: key or access problem — never retried
    "rate_limit",  # 429: queue and Retry-After
    "server",  # 5xx
    "timeout",
    "unavailable",  # network/DNS/provider down
    "bad_request",  # 400/404/422: request or model id invalid
    "budget",  # 402 or local spend cap
    "policy",  # blocked locally by free_only / profile policy before any network call
    "malformed",  # provider answered but the payload is unusable
}


class ProviderError(Exception):
    def __init__(
        self,
        kind: str,
        message: str,
        *,
        status: int | None = None,
        retry_after_s: float | None = None,
        provider: str | None = None,
        model_id: str | None = None,
    ):
        assert kind in ERROR_KINDS, kind
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after_s = retry_after_s
        self.provider = provider
        self.model_id = model_id

    @property
    def retryable(self) -> bool:
        return self.kind in {"rate_limit", "server", "timeout", "unavailable"}


class AIProvider(Protocol):
    name: str
    model_id: str

    async def generate(self, request: ProviderRequest) -> ProviderResponse: ...

    def capabilities(self) -> dict[str, bool]: ...


def sanitize(message: str, secrets: list[str | None]) -> str:
    """Remove secrets from any provider error text before it reaches logs or DTOs."""
    text = message
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    return text[:500]

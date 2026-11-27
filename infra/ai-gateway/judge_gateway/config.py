"""Gateway configuration (server side only). Values come from environment variables.

Secrets (provider keys) are read by name and never returned by any route or log line.
Competition tokens are stored as SHA-256 hashes with expiry; the plaintext token is shown
once at issue time. A token in the jury package is NOT a strong secret: all caps below apply
regardless of who holds it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field


class TokenRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token_id: str = Field(min_length=4, max_length=64)
    sha256: str = Field(min_length=64, max_length=64)
    expires_at: datetime
    label: str = ""
    max_requests: int = Field(default=500, ge=1)
    revoked: bool = False


class GatewayLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_body_bytes: int = 262_144
    max_messages: int = 40
    max_context_chars: int = 24_000
    max_tool_iterations: int = 6
    global_requests_per_day: int = 1_500
    global_spend_usd: Decimal = Decimal("0")
    per_token_rpm: int = 20
    per_session_rpm: int = 10
    per_session_requests: int = 120
    per_ip_rpm: int = 30
    max_concurrency: int = 4
    request_deadline_s: float = 40.0


@dataclass
class GatewayConfig:
    mode: str = "free_only"
    provider: str = "gemini"
    models: list[str] = field(default_factory=lambda: ["gemini-3.5-flash-lite", "gemini-3.8-flash"])
    prompt_version: str = ""
    tokens: list[TokenRecord] = field(default_factory=list)
    limits: GatewayLimits = field(default_factory=GatewayLimits)
    trust_forwarded_for: bool = False
    provider_key_env: str = "GEMINI_API_KEY"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "GatewayConfig":
        from glassflow.modules.intelligence.assistant.prompts import PROMPT_VERSION

        env = env if env is not None else os.environ
        provider = env.get("GATEWAY_PROVIDER", "gemini")
        default_models = "gemini-3.5-flash-lite,gemini-3.8-flash" if provider == "gemini" else "nvidia/nemotron-3.5-super-vl:free"
        tokens: list[TokenRecord] = []
        path = env.get("GATEWAY_TOKENS_FILE")
        if path and Path(path).is_file():
            tokens = [TokenRecord.model_validate(item) for item in json.loads(Path(path).read_text(encoding="utf-8"))]
        limits = GatewayLimits(
            global_requests_per_day=int(env.get("GATEWAY_GLOBAL_REQUESTS_PER_DAY", "1500")),
            global_spend_usd=Decimal(env.get("GATEWAY_GLOBAL_SPEND_USD", "0")),
            per_session_rpm=int(env.get("GATEWAY_PER_SESSION_RPM", "10")),
            per_ip_rpm=int(env.get("GATEWAY_PER_IP_RPM", "30")),
            max_concurrency=int(env.get("GATEWAY_MAX_CONCURRENCY", "4")),
        )
        return cls(
            mode=env.get("GATEWAY_MODE", "free_only"),
            provider=provider,
            models=[m.strip() for m in env.get("GATEWAY_MODELS", default_models).split(",") if m.strip()],
            prompt_version=env.get("GATEWAY_PROMPT_VERSION", PROMPT_VERSION),
            tokens=tokens,
            limits=limits,
            trust_forwarded_for=env.get("GATEWAY_TRUST_FORWARDED_FOR", "0") == "1",
            provider_key_env="GEMINI_API_KEY" if provider == "gemini" else "OPENROUTER_API_KEY",
        )

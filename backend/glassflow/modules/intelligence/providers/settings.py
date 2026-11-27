"""AI profile composition from settings and a secret provider.

Pro owns persistent settings and the Windows secret store; this module only defines what a
profile contains and how providers are built from it. Secrets are fetched by name at build
time and never placed in DTOs, logs, manifests or the browser bundle.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping, Protocol

from .base import AIProvider
from .gateway_client import GatewayProvider
from .gemini import GeminiProvider
from .openrouter import OpenRouterProvider
from .policy import AIProfile, MemoryLedger, ModelRef, ResilientClient, UsageLedger, validate_profile

DEFAULT_GEMINI_PRIMARY = "gemini-3.8-flash"
DEFAULT_GEMINI_FALLBACK = "gemini-3.5-flash-lite"
DEFAULT_OPENROUTER_FREE = "google/gemma-4-31b-it:free"
SECRET_NAMES = {"gemini": "GEMINI_API_KEY", "openrouter": "OPENROUTER_API_KEY", "judge_gateway": "GLASSFLOW_GATEWAY_TOKEN"}


class SecretProvider(Protocol):
    def get(self, name: str) -> str | None: ...


class EnvSecrets:
    """Session-memory secrets from the process environment (never persisted by this module)."""

    def __init__(self, env: Mapping[str, str] | None = None):
        self._env = env if env is not None else os.environ

    def get(self, name: str) -> str | None:
        value = self._env.get(name)
        return value.strip() if value and value.strip() else None


def _ref(text: str) -> ModelRef:
    provider, _, model = text.strip().partition(":")
    return ModelRef(provider=provider, model_id=model)  # type: ignore[arg-type]


def profile_from_env(env: Mapping[str, str] | None = None, secrets: SecretProvider | None = None) -> AIProfile:
    env = env if env is not None else os.environ
    secrets = secrets or EnvSecrets(env)
    mode = env.get("GLASSFLOW_AI_MODE", "free_only")
    provider = env.get("GLASSFLOW_AI_PROVIDER", "auto")
    model = env.get("GLASSFLOW_AI_MODEL")
    fallbacks_raw = env.get("GLASSFLOW_AI_FALLBACKS")
    primary: ModelRef | None = None
    fallbacks: list[ModelRef] = []
    if provider == "none":
        primary = None
    elif provider == "judge_gateway":
        primary = ModelRef(provider="judge_gateway", model_id="gateway-pinned")
    elif provider in {"gemini", "openrouter"}:
        default = DEFAULT_GEMINI_PRIMARY if provider == "gemini" else DEFAULT_OPENROUTER_FREE
        primary = ModelRef(provider=provider, model_id=model or default)
    else:  # auto: first provider with a configured key
        if secrets.get(SECRET_NAMES["gemini"]):
            primary = ModelRef(provider="gemini", model_id=model or DEFAULT_GEMINI_PRIMARY)
            fallbacks.append(ModelRef(provider="gemini", model_id=DEFAULT_GEMINI_FALLBACK))
            if secrets.get(SECRET_NAMES["openrouter"]):
                fallbacks.append(ModelRef(provider="openrouter", model_id=DEFAULT_OPENROUTER_FREE))
        elif secrets.get(SECRET_NAMES["openrouter"]):
            primary = ModelRef(provider="openrouter", model_id=model or DEFAULT_OPENROUTER_FREE)
        elif env.get("GLASSFLOW_GATEWAY_URL") and secrets.get(SECRET_NAMES["judge_gateway"]):
            primary = ModelRef(provider="judge_gateway", model_id="gateway-pinned")
    if fallbacks_raw is not None:
        fallbacks = [_ref(item) for item in fallbacks_raw.split(",") if item.strip()]

    def _int(name: str, default: int | None) -> int | None:
        value = env.get(name)
        return int(value) if value else default

    return AIProfile(
        name=env.get("GLASSFLOW_AI_PROFILE", "default"),
        mode=mode if mode in {"free_only", "paid_enabled"} else "free_only",
        primary=primary,
        fallbacks=[f for f in fallbacks if primary is None or f.label != primary.label],
        budget_usd=Decimal(env.get("GLASSFLOW_AI_BUDGET_USD", "0")),
        rpm=_int("GLASSFLOW_AI_RPM", 10),
        tpm=_int("GLASSFLOW_AI_TPM", 200_000),
        rpd=_int("GLASSFLOW_AI_RPD", 200),
        request_timeout_s=float(env.get("GLASSFLOW_AI_TIMEOUT_S", "20")),
        turn_deadline_s=float(env.get("GLASSFLOW_AI_DEADLINE_S", "45")),
    )


@dataclass
class AIRuntime:
    profile: AIProfile
    client: ResilientClient | None
    status: str  # available | no_key | invalid_profile | disabled
    reason_ru: str | None
    key_configured: dict[str, bool] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.client is not None and self.status == "available"


def build_runtime(
    profile: AIProfile,
    secrets: SecretProvider,
    *,
    prompt_version: str,
    ledger: UsageLedger | None = None,
    session_id: str = "local",
    env: Mapping[str, str] | None = None,
    providers_override: dict[str, AIProvider] | None = None,
) -> AIRuntime:
    env = env if env is not None else os.environ
    ledger = ledger or MemoryLedger()
    keys = {provider: bool(secrets.get(name)) for provider, name in SECRET_NAMES.items()}
    if profile.primary is None:
        return AIRuntime(profile, None, "disabled", "AI-профиль не настроен: работает ограниченный локальный режим.", keys)
    errors = validate_profile(profile)
    if errors:
        return AIRuntime(profile, None, "invalid_profile", errors[0], keys)
    providers: dict[str, AIProvider] = dict(providers_override or {})
    if not providers:
        for ref in [profile.primary, *profile.fallbacks]:
            secret = secrets.get(SECRET_NAMES[ref.provider])
            if not secret:
                continue
            if ref.provider == "gemini":
                providers[ref.label] = GeminiProvider(ref.model_id, secret)
            elif ref.provider == "openrouter":
                providers[ref.label] = OpenRouterProvider(ref.model_id, secret)
            elif ref.provider == "judge_gateway":
                url = env.get("GLASSFLOW_GATEWAY_URL")
                if url:
                    providers[ref.label] = GatewayProvider(url, secret, prompt_version=prompt_version, session_id=session_id)
    if not providers:
        return AIRuntime(profile, None, "no_key", "Ключ провайдера не задан: работает ограниченный локальный режим.", keys)
    client = ResilientClient(profile=profile, providers=providers, ledger=ledger, prompt_version=prompt_version)
    if not client.chain():
        return AIRuntime(profile, None, "no_key", "Нет ключа для выбранной модели профиля.", keys)
    return AIRuntime(profile, client, "available", None, keys)

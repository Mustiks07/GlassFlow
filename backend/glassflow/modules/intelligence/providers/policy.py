"""AI profiles, free_only policy, quotas, retries and the usage ledger.

- Default mode is ``free_only`` with a zero budget. A paid model is rejected *before* any
  network call; there is no hidden paid fallback and no random free router.
- Every model call (turn, tool follow-up, verifier, retry) passes one limiter that counts
  RPM, TPM, RPD and concurrency for the profile; keys are never rotated to bypass limits.
- 401/403 are not retried; 429 honours Retry-After; 5xx/timeouts use bounded exponential
  backoff with jitter (≤2 retries by default), then an already verified free fallback model.
- Each attempt is written to the usage ledger with the actual model, latency, queue time,
  tokens and cost; unknown cost stays ``None``.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .base import AIProvider, ProviderError, ProviderRequest, ProviderResponse
from .basisweb import QUOTA_RATES, reserve_quota, usage_quota

_ATTEMPT_SINK: ContextVar[list[dict] | None] = ContextVar("glassflow_model_attempts", default=None)


@contextmanager
def capture_attempts(sink: list[dict]):
    token = _ATTEMPT_SINK.set(sink)
    try:
        yield
    finally:
        _ATTEMPT_SINK.reset(token)

# Free-tier eligibility as published on the official pricing pages, checked 2026-11-27
# (docs/ai/MODEL_SELECTION.md). Availability in a given account/project is a separate check.
GEMINI_FREE_TIER_MODELS = {
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-4-hydrogen",
}
MIN_ATTEMPT_SECONDS = 2.0
LONG_RETRY_AFTER_S = 60.0  # a Retry-After beyond this (daily quota) is not waited for inside a turn  # do not start an attempt that cannot finish inside the turn deadline
OPENROUTER_FORBIDDEN_ROUTERS = {"openrouter/free", "openrouter/auto", "openrouter/auto:free"}


class PaidPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_usd_per_1m: Decimal
    output_usd_per_1m: Decimal
    source_url: str
    checked_on: str


class ModelRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["gemini", "openrouter", "judge_gateway", "basisweb"]
    model_id: str = Field(min_length=1, max_length=200)
    paid_price: PaidPrice | None = None
    verified_on: str | None = None  # date of a successful live contract check

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model_id}"


class AIProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "default"
    mode: Literal["free_only", "paid_enabled"] = "free_only"
    primary: ModelRef | None = None
    fallbacks: list[ModelRef] = Field(default_factory=list, max_length=4)
    budget_usd: Decimal = Decimal("0")
    included_quota_enabled: bool = False
    quota_token_budget: int = Field(default=1_000_000, ge=1, le=5_000_000)
    rpm: int | None = Field(default=10, ge=1)
    tpm: int | None = Field(default=200_000, ge=1)
    rpd: int | None = Field(default=200, ge=1)
    max_concurrency: int = Field(default=2, ge=1, le=16)
    max_output_tokens: int = Field(default=1024, ge=64, le=8192)
    request_timeout_s: float = Field(default=15.0, gt=0, le=120)
    turn_deadline_s: float = Field(default=45.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=4)
    max_tool_iterations: int = Field(default=6, ge=1, le=12)
    backoff_base_s: float = Field(default=1.0, gt=0, le=30)


def model_is_free(ref: ModelRef) -> bool:
    if ref.provider == "gemini":
        return ref.model_id in GEMINI_FREE_TIER_MODELS
    if ref.provider == "openrouter":
        return ref.model_id.endswith(":free") and ref.model_id not in OPENROUTER_FORBIDDEN_ROUTERS
    if ref.provider == "judge_gateway":
        return True  # the gateway enforces its own server-side free_only policy
    return False


def validate_profile(profile: AIProfile) -> list[str]:
    errors: list[str] = []
    if profile.primary is None:
        return ["Не выбрана модель: AI-профиль выключен, работает ограниченный локальный режим."]
    refs = [profile.primary, *profile.fallbacks]
    for ref in refs:
        included = ref.provider == "basisweb" and profile.included_quota_enabled and ref.model_id in QUOTA_RATES
        if ref.provider == "basisweb" and not included:
            errors.append(f"{ref.label}: нужен явный opt-in включенной квоты и проверенный тариф модели.")
        if ref.provider == "openrouter" and ref.model_id in OPENROUTER_FORBIDDEN_ROUTERS:
            errors.append(f"{ref.label}: случайный маршрутизатор запрещен; нужен конкретный model_id.")
        if profile.mode == "free_only" and not model_is_free(ref) and not included:
            errors.append(f"{ref.label}: модель не входит в проверенный бесплатный список при free_only.")
        if profile.mode == "paid_enabled" and not model_is_free(ref) and not included and ref.paid_price is None:
            errors.append(f"{ref.label}: для платной модели нужен тариф с датой и источником.")
    if profile.mode == "paid_enabled" and profile.budget_usd <= 0:
        errors.append("Платный режим требует явного положительного бюджета.")
    if profile.mode == "free_only" and profile.budget_usd != 0:
        errors.append("В режиме free_only денежный лимит должен быть равен нулю.")
    labels = [ref.label for ref in refs]
    if len(labels) != len(set(labels)):
        errors.append("Модели в списке резервов повторяются.")
    return errors


@dataclass
class LedgerEntry:
    call_id: str
    created_at: str
    purpose: str
    provider: str
    model_id: str
    attempt: int
    status: str  # ok | error | rejected
    error_kind: str | None
    latency_ms: int | None
    queue_ms: int
    input_tokens: int | None
    output_tokens: int | None
    thought_tokens: int | None
    cached_tokens: int | None
    cost_usd: Decimal | None
    cost_source: str
    prompt_version: str
    correlation_id: str | None = None
    error_message: str | None = None  # sanitized, short; in-memory diagnostics only (not persisted)


class UsageLedger(Protocol):
    def record(self, entry: LedgerEntry) -> None: ...


class MemoryLedger:
    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def record(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)


class RateLimiter:
    """Sliding-window RPM/TPM/RPD with a concurrency cap. Waits within the turn deadline."""

    def __init__(self, rpm: int | None, tpm: int | None, rpd: int | None, concurrency: int, clock: Callable[[], float] = time.monotonic):
        self.rpm, self.tpm, self.rpd = rpm, tpm, rpd
        self.clock = clock
        self.minute: deque[tuple[float, int]] = deque()
        self.day: deque[float] = deque()
        self.semaphore = asyncio.Semaphore(concurrency)
        self.lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        while self.minute and now - self.minute[0][0] >= 60:
            self.minute.popleft()
        while self.day and now - self.day[0] >= 86_400:
            self.day.popleft()

    def wait_needed(self, estimated_tokens: int, now: float | None = None) -> float:
        now = self.clock() if now is None else now
        self._prune(now)
        if self.rpd is not None and len(self.day) >= self.rpd:
            return float("inf")
        waits = [0.0]
        if self.rpm is not None and len(self.minute) >= self.rpm:
            waits.append(60 - (now - self.minute[0][0]))
        if self.tpm is not None:
            used = sum(tokens for _, tokens in self.minute)
            if used + estimated_tokens > self.tpm and self.minute:
                waits.append(60 - (now - self.minute[0][0]))
        return max(waits)

    async def acquire(self, estimated_tokens: int, deadline: float) -> float:
        start = self.clock()
        while True:
            if self.clock() >= deadline:
                raise ProviderError("timeout", "Истек общий срок ответа AI в очереди лимитера.")
            async with self.lock:
                wait = self.wait_needed(estimated_tokens)
                if wait <= 0:
                    now = self.clock()
                    self.minute.append((now, estimated_tokens))
                    self.day.append(now)
                    return self.clock() - start
            if wait == float("inf"):
                raise ProviderError("rate_limit", "Исчерпан дневной лимит запросов профиля (RPD).")
            if self.clock() + wait > deadline:
                raise ProviderError("rate_limit", "Лимит запросов в минуту: ожидание превышает срок ответа.", retry_after_s=wait)
            await asyncio.sleep(min(wait, 1.0))

    def correct_tokens(self, estimated: int, actual: int | None) -> None:
        if actual is None or not self.minute:
            return
        for index in range(len(self.minute) - 1, -1, -1):
            stamp, tokens = self.minute[index]
            if tokens == estimated:
                self.minute[index] = (stamp, actual)
                return


def estimate_tokens(request: ProviderRequest) -> int:
    chars = len(request.system) + sum(len(m.text or "") + sum(len(c.arguments_json) for c in m.tool_calls) for m in request.messages)
    chars += sum(len(str(tool.parameters)) + len(tool.description) for tool in request.tools)
    return chars // 3 + request.max_output_tokens


def backoff_delay(error: ProviderError, attempt: int, base: float, rng: random.Random) -> float:
    if error.kind == "rate_limit" and error.retry_after_s is not None:
        return min(error.retry_after_s, 60.0) + rng.uniform(0, 0.25)
    return base * (2**attempt) + rng.uniform(0, base)


@dataclass
class CallOutcome:
    response: ProviderResponse
    attempts: int
    fallback_used: bool
    model_label: str


@dataclass
class ResilientClient:
    profile: AIProfile
    providers: dict[str, AIProvider]  # label -> provider instance
    ledger: UsageLedger
    prompt_version: str
    rng: random.Random = field(default_factory=lambda: random.Random(17))
    sleep: Callable[[float], object] = asyncio.sleep
    clock: Callable[[], float] = time.monotonic
    spent_usd: Decimal = Decimal("0")
    quota_tokens_spent: int = 0
    cooldown_s: float = 60.0  # circuit breaker: an overloaded model is skipped for this long

    def __post_init__(self) -> None:
        self.limiter = RateLimiter(self.profile.rpm, self.profile.tpm, self.profile.rpd, self.profile.max_concurrency, self.clock)
        self.unhealthy_until: dict[str, float] = {}

    def chain(self) -> list[str]:
        """Verified models in profile order; models in breaker cooldown go last (still usable)."""
        if self.profile.primary is None:
            return []
        refs = [self.profile.primary, *self.profile.fallbacks]
        if self.profile.mode == "free_only":
            refs = [ref for ref in refs if model_is_free(ref) or
                    (ref.provider == "basisweb" and self.profile.included_quota_enabled and ref.model_id in QUOTA_RATES)]
        labels = [ref.label for ref in refs if ref.label in self.providers]
        now = self.clock()
        healthy = [label for label in labels if self.unhealthy_until.get(label, 0) <= now]
        return healthy + [label for label in labels if label not in healthy]

    async def call(self, request: ProviderRequest, *, deadline: float, correlation_id: str | None = None) -> CallOutcome:
        errors = validate_profile(self.profile)
        if errors:
            self._log(request, self.profile.primary.label if self.profile.primary else "none:none", 0, "rejected", "policy", None, 0, None, correlation_id)
            raise ProviderError("policy", errors[0])
        chain = self.chain()
        if not chain:
            raise ProviderError("unavailable", "Нет настроенного провайдера с ключом для AI-профиля.")
        now = self.clock()
        if all(self.unhealthy_until.get(label, 0) > deadline for label in chain):
            # every verified model is out of quota/overloaded beyond this turn: fail fast, no network
            wait = min(self.unhealthy_until[label] for label in chain) - now
            raise ProviderError("rate_limit", "Квота или доступность всех моделей профиля исчерпана; работает локальный режим.",
                                retry_after_s=wait)
        last_error: ProviderError | None = None
        attempts = 0
        for index, label in enumerate(chain):
            provider = self.providers[label]
            # Fair share of the remaining time so a failing primary cannot starve verified fallbacks.
            models_left = len(chain) - index
            model_deadline = self.clock() + (deadline - self.clock()) / models_left
            for attempt in range(self.profile.max_retries + 1):
                remaining = deadline - self.clock()
                if remaining < MIN_ATTEMPT_SECONDS:
                    raise last_error or ProviderError("timeout", "Истек общий срок ответа AI.")
                if attempt > 0 and self.clock() >= model_deadline and models_left > 1:
                    break
                included = label.startswith("basisweb:") and self.profile.included_quota_enabled
                if self.profile.mode == "paid_enabled" and self.spent_usd >= self.profile.budget_usd and not self._is_free(label) and not included:
                    raise ProviderError("budget", "Исчерпан денежный бюджет платного профиля.")
                estimated = estimate_tokens(request)
                attempts += 1
                try:
                    queue_s = await asyncio.wait_for(self.limiter.acquire(estimated, deadline),
                                                     timeout=max(0, deadline - self.clock()))
                except TimeoutError:
                    self._log(request, label, attempt, "error", "timeout", None, 0, None, correlation_id)
                    raise ProviderError("timeout", "Истек общий срок ответа AI в очереди лимитера.") from None
                except ProviderError as exc:
                    self._log(request, label, attempt, "error", exc.kind, None, 0, None, correlation_id)
                    raise
                started = self.clock()
                reservation = 0
                network_started = False
                sent_at = None
                try:
                    # Semaphore waiting belongs to the same absolute turn budget.
                    # Recompute the HTTP allowance after waiting; no per-call grace
                    # or minimum timeout can extend the deadline.
                    async with asyncio.timeout(max(0, deadline - self.clock())):
                        async with self.limiter.semaphore:
                            remaining = deadline - self.clock()
                            if remaining <= 0:
                                raise ProviderError("timeout", "Истек общий срок ответа AI до отправки запроса.")
                            timeout = min(self.profile.request_timeout_s, remaining)
                            if included:
                                reservation = reserve_quota(request, provider.model_id)
                                if self.quota_tokens_spent + reservation > self.profile.quota_token_budget:
                                    raise ProviderError("budget", "Лимит включенной квоты исчерпан; новый вызов не отправлен.")
                                # Reserve atomically before awaiting I/O, including failures and cancellation.
                                self.quota_tokens_spent += reservation
                            network_started = True
                            sent_at = self.clock()
                            response = await asyncio.wait_for(provider.generate(_with_timeout(request, timeout)), timeout=timeout)
                except asyncio.CancelledError:
                    if network_started:
                        self._log(request, label, attempt, "error", "timeout", None, int((queue_s + sent_at - started) * 1000),
                                  int((self.clock() - sent_at) * 1000), correlation_id, "Отменен запрос; расход квоты неизвестен.")
                    raise
                except TimeoutError:
                    error = ProviderError("timeout", "Тайм-аут запроса к модели." if network_started else
                                          "Истек общий срок ответа AI в очереди провайдера.", provider=provider.name, model_id=provider.model_id)
                except ProviderError as exc:
                    error = exc
                except Exception as exc:  # network stack errors are mapped, never leaked
                    error = ProviderError("unavailable", f"Сбой соединения: {type(exc).__name__}: {str(exc)[:120]}", provider=provider.name)
                else:
                    latency = int((self.clock() - sent_at) * 1000)
                    response.latency_ms = response.latency_ms or latency
                    self.limiter.correct_tokens(estimated, _total_tokens(response))
                    if response.usage.cost_usd is not None:
                        self.spent_usd += response.usage.cost_usd
                    if included:
                        actual_quota = usage_quota(response.usage, provider.model_id)
                        if actual_quota is not None:
                            self.quota_tokens_spent += actual_quota - reservation
                    self._log(request, label, attempt, "ok", None, response, int((queue_s + sent_at - started) * 1000), latency, correlation_id)
                    self.unhealthy_until.pop(label, None)
                    return CallOutcome(response, attempts, label != self.chain_order()[0], label)
                latency = int((self.clock() - sent_at) * 1000) if network_started else None
                queue_ms = int((queue_s + (sent_at if network_started else self.clock()) - started) * 1000)
                self._log(request, label, attempt, "error", error.kind, None, queue_ms, latency, correlation_id, str(error)[:200])
                last_error = error
                if not error.retryable:
                    if error.kind in {"auth", "bad_request", "budget"}:
                        break  # try the next verified model only for model-specific problems
                    raise error
                if error.kind == "rate_limit" and (error.retry_after_s or 0) > LONG_RETRY_AFTER_S:
                    break  # e.g. daily quota: waiting inside a turn is pointless; breaker keeps it out until then
                if attempt < self.profile.max_retries:
                    delay = backoff_delay(error, attempt, self.profile.backoff_base_s, self.rng)
                    if self.clock() + delay >= deadline:
                        break
                    await self.sleep(delay)
            if last_error and last_error.retryable and network_started:
                cooldown = max(self.cooldown_s, last_error.retry_after_s or 0)
                self.unhealthy_until[label] = self.clock() + cooldown
            if last_error and last_error.kind == "auth" and index == len(chain) - 1:
                raise last_error
        raise last_error or ProviderError("unavailable", "AI недоступен.")

    def chain_order(self) -> list[str]:
        """Profile order without breaker reordering (to report whether a fallback answered)."""
        refs = [r for r in [self.profile.primary, *self.profile.fallbacks] if r is not None]
        return [ref.label for ref in refs if ref.label in self.providers] or [""]

    def _is_free(self, label: str) -> bool:
        refs = [r for r in [self.profile.primary, *self.profile.fallbacks] if r and r.label == label]
        return bool(refs) and model_is_free(refs[0])

    def _log(self, request, label, attempt, status, kind, response, queue_ms, latency, correlation_id, message=None) -> None:
        provider, _, model = label.partition(":")
        usage = response.usage if response else None
        sink = _ATTEMPT_SINK.get()
        # Preflight/queue rejection has no HTTP attempt. A failed HTTP call does.
        if sink is not None and latency is not None:
            sink.append({"provider": provider, "model_id": response.model_id if response else model,
                         "status": status, "error_kind": kind})
        self.ledger.record(
            LedgerEntry(
                call_id=str(uuid.uuid4()),
                created_at=datetime.now(UTC).isoformat(),
                purpose=request.purpose,
                provider=provider,
                model_id=response.model_id if response else model,
                attempt=attempt,
                status=status,
                error_kind=kind,
                latency_ms=latency,
                queue_ms=queue_ms,
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                thought_tokens=usage.thought_tokens if usage else None,
                cached_tokens=usage.cached_tokens if usage else None,
                cost_usd=usage.cost_usd if usage else None,
                cost_source=usage.cost_source if usage else "no_response",
                prompt_version=self.prompt_version,
                correlation_id=correlation_id,
                error_message=message,
            )
        )


def _with_timeout(request: ProviderRequest, timeout: float) -> ProviderRequest:
    return ProviderRequest(
        system=request.system,
        messages=request.messages,
        tools=request.tools,
        max_output_tokens=request.max_output_tokens,
        temperature=request.temperature,
        timeout_s=timeout,
        purpose=request.purpose,
    )


def _total_tokens(response: ProviderResponse) -> int | None:
    usage = response.usage
    if usage.input_tokens is None and usage.output_tokens is None:
        return None
    return (usage.input_tokens or 0) + (usage.output_tokens or 0) + (usage.thought_tokens or 0)

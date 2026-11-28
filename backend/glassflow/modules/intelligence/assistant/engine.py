"""Turn orchestration: deterministic facts first, online AI only where it adds understanding.

1. The local engine analyses the request. Recognized, unambiguous requests are answered from
   Pricing/KB facts (``deterministic``) — fast, reproducible and quota-free.
2. If the request is not recognized (or the product was not found) and an AI profile is
   available, the tool-calling model runs (``llm_tools``); its text is shown only after
   verify_answer accepts it.
3. Provider errors, iteration caps and unsupported claims fall back to the deterministic
   answer or a concrete clarification (``fallback``); the reply states the limited mode.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from ..catalog.kb import KnowledgeBase
from ..catalog.mapping import MappingDecision
from ..catalog.text import normalize
from ..ports_consumed import CrmPort, InventoryPort, ScenarioPort
from ..providers.policy import capture_attempts
from ..providers.settings import AIRuntime
from .llm import LlmOutcome, run_llm_turn
from .local import MAX_SENTENCES, LocalEngine, LocalOutcome, TurnContext
from .prompts import PROMPT_VERSION
from .tools import ASSISTANT_TOOLSET, ToolContext

ENGINE_VERSION = "dialog-engine-v1"


class AnswerCache:
    """Per-service LRU cache of verified AI answers. Inventory-dependent answers are never cached."""

    def __init__(self, capacity: int = 512):
        self.capacity = capacity
        self._data: OrderedDict[str, dict] = OrderedDict()

    def get(self, key: str) -> dict | None:
        value = self._data.get(key)
        if value is not None:
            self._data.move_to_end(key)
        return value

    def put(self, key: str, value: dict) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.capacity:
            self._data.popitem(last=False)


def cache_key(text: str, kb_version: str, model_chain: list[str], context: dict[str, str]) -> str:
    """Content-based key: normalized text + KB/prompt/model/engine versions + meaningful context.

    The question/app ID is deliberately not part of the key.
    """
    meaningful = {k: v for k, v in sorted(context.items()) if k not in {"customer_id"}}
    payload = json.dumps(
        {
            "text": normalize(text),
            "kb": kb_version,
            "prompt": PROMPT_VERSION,
            "engine": ENGINE_VERSION,
            "models": model_chain,
            "context": meaningful,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class TurnResult:
    answer: str
    clarification: str | None
    status: str
    answer_path: str
    mode: str
    provider: str | None
    model_id: str | None
    verifier_status: str
    local: LocalOutcome
    llm: LlmOutcome | None
    ai_unavailable_reason: str | None
    latency_ms: int
    cache_hit: bool = False
    tool_records: list[dict] = field(default_factory=list)
    tool_context: ToolContext | None = None
    model_attempts: list[dict] = field(default_factory=list)


def _limit_sentences(text: str) -> str:
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p]
    return " ".join(parts[:MAX_SENTENCES])


class AssistantEngine:
    def __init__(
        self,
        kb: KnowledgeBase,
        mappings: dict[str, MappingDecision],
        *,
        dataset_id: str,
        runtime: AIRuntime | None = None,
        inventory: InventoryPort | None = None,
        crm: CrmPort | None = None,
        scenario: ScenarioPort | None = None,
        cache: AnswerCache | None = None,
    ):
        self.kb = kb
        self.mappings = mappings
        self.dataset_id = dataset_id
        self.runtime = runtime
        self.inventory = inventory
        self.crm = crm
        self.scenario = scenario
        self.cache = cache if cache is not None else AnswerCache()
        self.local = LocalEngine(kb, mappings, dataset_id=dataset_id, inventory=inventory)

    def _needs_ai(self, local: LocalOutcome) -> bool:
        if not local.recognized or local.status == "limited":
            return True
        return any(f.value == "product_not_in_kb" for f in local.facts.facts)

    async def turn(
        self,
        text: str,
        context: TurnContext | None = None,
        *,
        inventory_mode: str = "none",
        allow_ai: bool = True,
        correlation_id: str | None = None,
        strategy: str = "hybrid",
    ) -> TurnResult:
        """strategy: ``hybrid`` (default; AI only for unrecognized requests) or ``ai_first``
        (evaluation of the online path: the model answers every turn, deterministic fallback)."""
        started = time.monotonic()
        local = self.local.respond(text, context, inventory_mode=inventory_mode)
        runtime = self.runtime
        ai_ready = bool(runtime and runtime.available and allow_ai)
        reason = None if ai_ready else (runtime.reason_ru if runtime and runtime.reason_ru else "AI-профиль не настроен.")
        if not allow_ai:
            reason = "AI отключен для этого запроса."
        mode = "online" if ai_ready else "local_limited"
        base = dict(local=local, ai_unavailable_reason=reason)

        def deterministic(path: str = "deterministic", verifier: str = "supported", llm=None, mode_value=mode, why=reason):
            return TurnResult(
                answer=local.answer,
                clarification=local.clarification,
                status=local.status,
                answer_path=path,
                mode=mode_value,
                provider=None,
                model_id=None,
                verifier_status=verifier,
                llm=llm,
                latency_ms=int((time.monotonic() - started) * 1000),
                local=local,
                ai_unavailable_reason=why,
                model_attempts=llm.model_attempts if llm else [],
            )

        if not ai_ready and strategy == "ai_first":
            return deterministic("fallback", "not_applicable", mode_value="local_limited")
        if not ai_ready or (strategy != "ai_first" and not self._needs_ai(local)):
            return deterministic()

        assert runtime is not None and runtime.client is not None
        chain = runtime.client.chain()
        key = cache_key(text, self.kb.version, chain, (context or TurnContext()).to_dict())
        cached = self.cache.get(key) if strategy != "ai_first" else None
        if cached is not None:
            return TurnResult(
                answer=cached["answer"], clarification=cached.get("clarification"), status=cached["status"],
                answer_path="llm_tools", mode="online", provider=cached.get("provider"), model_id=cached.get("model_id"),
                verifier_status="supported", llm=None, latency_ms=int((time.monotonic() - started) * 1000),
                cache_hit=True, **base,
            )
        ctx = ToolContext(
            self.kb, self.mappings, self.dataset_id, self.inventory, self.crm, self.scenario, user_text=text
        )
        deadline = time.monotonic() + runtime.profile.turn_deadline_s
        tool_names = [name for name in ASSISTANT_TOOLSET if not (name == "find_remnants" and inventory_mode == "none")]
        attempts: list[dict] = []
        with capture_attempts(attempts):
            llm = await run_llm_turn(
                runtime.client, ctx, text, (context or TurnContext()).to_dict(), deadline=deadline,
                correlation_id=correlation_id, tool_names=tool_names,
            )
        llm.model_attempts = attempts
        llm.model_calls = len(attempts)
        if llm.status == "provider_error":
            why = llm.error.args[0] if llm.error else "AI недоступен."
            return deterministic("fallback", "not_applicable", llm, "local_limited", why)
        if llm.status != "final" or not llm.answer:
            verifier = "unsupported_replaced" if llm.status == "verifier_rejected" else "not_applicable"
            return deterministic("fallback", verifier, llm)
        # Model tools cannot turn a user's unresolved product/processing choice
        # into a final offer. The same mandatory-domain gate applies in both modes.
        if local.status == "clarification" and local.missing_parameters and (
            not llm.clarification or ctx.last_quote is not None
        ):
            llm.status = "verifier_rejected"
            return deterministic("fallback", "unsupported_replaced", llm)
        answer = _limit_sentences(llm.answer)
        status = "manager_handoff" if llm.needs_manager else ("clarification" if llm.clarification else "answered")
        result = TurnResult(
            answer=answer,
            clarification=llm.clarification,
            status=status,
            answer_path="llm_tools",
            mode="online",
            provider=llm.provider,
            model_id=llm.model_id,
            verifier_status="supported",
            llm=llm,
            latency_ms=int((time.monotonic() - started) * 1000),
            tool_context=ctx,
            model_attempts=attempts,
            **base,
        )
        result.ai_unavailable_reason = None
        if not ctx.remnant_checked:
            self.cache.put(
                key,
                {
                    "answer": answer,
                    "clarification": llm.clarification,
                    "status": status,
                    "provider": llm.provider,
                    "model_id": llm.model_id,
                },
            )
        return result

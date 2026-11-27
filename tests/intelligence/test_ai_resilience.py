"""T34/T35 with scripted providers (mock-provider tests; NOT a live network check)."""

import asyncio
import time
from decimal import Decimal

import pytest

from glassflow.modules.intelligence.assistant.engine import AssistantEngine
from glassflow.modules.intelligence.assistant.tools import ToolContext, execute_tool
from glassflow.modules.intelligence.providers.base import ProviderError
from glassflow.modules.intelligence.providers.policy import (
    AIProfile,
    MemoryLedger,
    ModelRef,
    ResilientClient,
    validate_profile,
)
from glassflow.modules.intelligence.providers.settings import AIRuntime, build_runtime, profile_from_env

from .fakes import ScriptedProvider, reply, tool_call


def profile(**kwargs) -> AIProfile:
    data = dict(
        primary=ModelRef(provider="gemini", model_id="gemini-3.8-flash"),
        fallbacks=[ModelRef(provider="openrouter", model_id="google/gemma-4-31b-it:free")],
        backoff_base_s=0.01,
        turn_deadline_s=10,
    )
    data.update(kwargs)
    return AIProfile(**data)


def runtime_with(providers: dict, prof: AIProfile | None = None, ledger=None) -> AIRuntime:
    prof = prof or profile()
    client = ResilientClient(profile=prof, providers=providers, ledger=ledger or MemoryLedger(), prompt_version="test", sleep=lambda s: asyncio.sleep(0))
    return AIRuntime(prof, client, "available", None, {"gemini": True, "openrouter": True})


def engine_with(kb, mappings, runtime) -> AssistantEngine:
    return AssistantEngine(kb, mappings, dataset_id="ds", runtime=runtime)


UNRECOGNIZED = "Хочу что-нибудь красивое на кухню, посоветуйте"


def run(coro):
    return asyncio.run(coro)


def test_free_only_rejects_paid_models_before_network():
    paid = profile(primary=ModelRef(provider="gemini", model_id="gemini-4-carbon"), fallbacks=[])
    assert validate_profile(paid)
    router = profile(primary=ModelRef(provider="openrouter", model_id="openrouter/free"), fallbacks=[])
    assert any("маршрутизатор" in e for e in validate_profile(router))
    provider = ScriptedProvider([reply(text="x")])
    client = ResilientClient(profile=paid, providers={"gemini:gemini-4-carbon": provider}, ledger=MemoryLedger(), prompt_version="t")
    with pytest.raises(ProviderError) as info:
        run(client.call(_req(), deadline=time.monotonic() + 5))
    assert info.value.kind == "policy"
    assert provider.requests == []  # nothing was sent


def test_free_only_chain_drops_paid_fallback():
    prof = profile(fallbacks=[ModelRef(provider="openrouter", model_id="anthropic/some-paid-model")])
    assert validate_profile(prof)  # profile with a paid fallback is invalid in free_only
    ok = profile()
    client = ResilientClient(profile=ok, providers={"gemini:gemini-3.8-flash": ScriptedProvider([]), "openrouter:google/gemma-4-31b-it:free": ScriptedProvider([])}, ledger=MemoryLedger(), prompt_version="t")
    assert client.chain() == ["gemini:gemini-3.8-flash", "openrouter:google/gemma-4-31b-it:free"]


def _req():
    from glassflow.modules.intelligence.providers.base import ChatMessage, ProviderRequest

    return ProviderRequest(system="s", messages=[ChatMessage(role="user", text="hi")])


def test_429_honours_retry_after_then_succeeds():
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    provider = ScriptedProvider([ProviderError("rate_limit", "429", retry_after_s=3.0), reply(text="ok")])
    ledger = MemoryLedger()
    client = ResilientClient(profile=profile(fallbacks=[]), providers={"gemini:gemini-3.8-flash": provider}, ledger=ledger, prompt_version="t", sleep=fake_sleep)
    outcome = run(client.call(_req(), deadline=time.monotonic() + 30))
    assert outcome.response.text == "ok" and outcome.attempts == 2
    assert 3.0 <= sleeps[0] < 3.3
    assert [e.status for e in ledger.entries] == ["error", "ok"]
    assert ledger.entries[0].error_kind == "rate_limit"


def test_server_errors_bounded_retries_then_verified_free_fallback():
    primary = ScriptedProvider([ProviderError("server", "500")] * 3)
    fallback = ScriptedProvider([reply(text="ok", model="google/gemma-4-31b-it:free")])
    ledger = MemoryLedger()
    client = ResilientClient(
        profile=profile(),
        providers={"gemini:gemini-3.8-flash": primary, "openrouter:google/gemma-4-31b-it:free": fallback},
        ledger=ledger, prompt_version="t", sleep=lambda s: asyncio.sleep(0),
    )
    outcome = run(client.call(_req(), deadline=time.monotonic() + 30))
    assert len(primary.requests) == 3  # 1 call + 2 retries, not more
    assert outcome.fallback_used and outcome.response.model_id == "google/gemma-4-31b-it:free"
    assert len(ledger.entries) == 4


def test_auth_error_is_not_retried():
    provider = ScriptedProvider([ProviderError("auth", "403")])
    client = ResilientClient(profile=profile(fallbacks=[]), providers={"gemini:gemini-3.8-flash": provider}, ledger=MemoryLedger(), prompt_version="t")
    with pytest.raises(ProviderError) as info:
        run(client.call(_req(), deadline=time.monotonic() + 5))
    assert info.value.kind == "auth" and len(provider.requests) == 1


def test_timeout_is_bounded():
    class Slow(ScriptedProvider):
        async def generate(self, request):
            self.requests.append(request)
            await asyncio.sleep(5)

    slow = Slow([])
    prof = profile(fallbacks=[], request_timeout_s=0.2, max_retries=1)
    client = ResilientClient(profile=prof, providers={"gemini:gemini-3.8-flash": slow}, ledger=MemoryLedger(), prompt_version="t", sleep=lambda s: asyncio.sleep(0))
    started = time.monotonic()
    with pytest.raises(ProviderError) as info:
        run(client.call(_req(), deadline=time.monotonic() + 5))
    assert info.value.kind == "timeout"
    assert time.monotonic() - started < 5
    assert len(slow.requests) == 2


def test_rate_limiter_counts_every_call():
    prof = profile(fallbacks=[], rpm=2, max_retries=0)
    provider = ScriptedProvider([reply(text="a"), reply(text="b"), reply(text="c")])
    client = ResilientClient(profile=prof, providers={"gemini:gemini-3.8-flash": provider}, ledger=MemoryLedger(), prompt_version="t")
    run(client.call(_req(), deadline=time.monotonic() + 5))
    run(client.call(_req(), deadline=time.monotonic() + 5))
    with pytest.raises(ProviderError) as info:
        run(client.call(_req(), deadline=time.monotonic() + 5))  # third call in the same minute
    assert info.value.kind == "rate_limit"


def test_llm_tool_loop_uses_pricing_and_verifier(kb, mappings):
    script = [
        reply(tool_call("search_catalog", {"query": "стекло бронза"})),
        reply(tool_call("calculate_quote", {"catalog_product_id": "steklo-bronza", "length_mm": 1000, "width_mm": 500, "quantity": 1})),
        reply(tool_call("submit_answer", {"answer_ru": "Стекло бронза 1000×500 мм: 0,5 м² × 12 000 ₸ = 6 000 ₸. Цена предварительная, подтверждает менеджер."})),
    ]
    provider = ScriptedProvider(script)
    runtime = runtime_with({"gemini:gemini-3.8-flash": provider})
    result = run(engine_with(kb, mappings, runtime).turn(UNRECOGNIZED))
    assert result.answer_path == "llm_tools" and result.mode == "online"
    assert "6 000" in result.answer
    assert f"{result.tool_context.last_quote.total:f}" == "6000.00"
    assert result.model_id == "scripted-model"


def test_llm_invented_price_is_replaced(kb, mappings):
    script = [
        reply(tool_call("search_catalog", {"query": "стекло бронза"})),
        reply(tool_call("submit_answer", {"answer_ru": "Стекло бронза стоит 5 000 ₸ за м², скидка 10% для вас."})),
    ]
    runtime = runtime_with({"gemini:gemini-3.8-flash": ScriptedProvider(script)})
    result = run(engine_with(kb, mappings, runtime).turn(UNRECOGNIZED))
    assert result.answer_path == "fallback" and result.verifier_status == "unsupported_replaced"
    assert "5 000" not in result.answer and "скидка 10" not in result.answer
    assert set(result.llm.verification.unsupported) >= {"number:5000", "claim:discount"}


def test_malformed_tool_json_and_forbidden_tools_are_rejected(kb, mappings):
    script = [
        reply(tool_call("calculate_quote", "{not json")),
        reply(tool_call("run_sql", {"query": "DROP TABLE x"})),
        reply(tool_call("calculate_quote", {"catalog_product_id": "steklo-bronza", "length_mm": -5, "width_mm": 10})),
        reply(tool_call("submit_answer", {"answer_ru": "Уточните, пожалуйста, толщину и размеры — передам менеджеру."})),
    ]
    runtime = runtime_with({"gemini:gemini-3.8-flash": ScriptedProvider(script)})
    result = run(engine_with(kb, mappings, runtime).turn(UNRECOGNIZED))
    codes = [e.error_code for e in result.llm.executions]
    assert codes[:3] == ["MALFORMED_TOOL_JSON", "TOOL_NOT_ALLOWED", "INVALID_TOOL_ARGUMENTS"]
    assert result.llm.tool_errors == 3
    assert result.answer_path == "llm_tools"


def test_iteration_cap_six_keeps_context_and_falls_back(kb, mappings):
    script = [reply(tool_call("search_catalog", {"query": f"стекло {i}"}, call_id=f"c{i}")) for i in range(10)]
    provider = ScriptedProvider(script)
    runtime = runtime_with({"gemini:gemini-3.8-flash": provider})
    result = run(engine_with(kb, mappings, runtime).turn(UNRECOGNIZED))
    assert len(provider.requests) == 6
    assert result.answer_path == "fallback" and result.answer
    assert result.local.context is not None


def test_unavailable_provider_gives_local_limited_mode(kb, mappings):
    runtime = runtime_with(
        {"gemini:gemini-3.8-flash": ScriptedProvider([ProviderError("unavailable", "dns")] * 3),
         "openrouter:google/gemma-4-31b-it:free": ScriptedProvider([ProviderError("unavailable", "dns")] * 3)}
    )
    result = run(engine_with(kb, mappings, runtime).turn(UNRECOGNIZED))
    assert result.mode == "local_limited" and result.answer_path == "fallback"
    assert result.ai_unavailable_reason
    known = run(engine_with(kb, mappings, runtime).turn("Сколько стоит Стекло 4 мм прозрачное за квадратный метр?"))
    assert "4 500" in known.answer and known.answer_path == "deterministic"


def test_t35_switch_provider_same_contracts(kb, mappings):
    answers = []
    for label in ["gemini:gemini-3.8-flash", "openrouter:google/gemma-4-31b-it:free"]:
        script = [
            reply(tool_call("calculate_quote", {"catalog_product_id": "steklo-bronza", "length_mm": 1000, "width_mm": 500}), model=label),
            reply(tool_call("submit_answer", {"answer_ru": "Стекло бронза 1000×500 мм — 6 000 ₸, предварительно."}), model=label),
        ]
        prof = profile(primary=ModelRef(provider=label.split(":")[0], model_id=label.split(":", 1)[1]), fallbacks=[])
        result = run(engine_with(kb, mappings, runtime_with({label: ScriptedProvider(script, model_id=label)}, prof)).turn(UNRECOGNIZED))
        answers.append((result.model_id, f"{result.tool_context.last_quote.total:f}", result.verifier_status))
    assert answers[0][1:] == answers[1][1:] == ("6000.00", "supported")
    assert answers[0][0] != answers[1][0]


def test_cache_key_is_content_based_not_id(kb, mappings):
    from glassflow.modules.intelligence.assistant.engine import cache_key

    a = cache_key("Сколько стоит стекло?", kb.version, ["m"], {})
    b = cache_key("сколько  стоит СТЕКЛО?", kb.version, ["m"], {})
    c = cache_key("Сколько стоит стекло?", "kb-other", ["m"], {})
    d = cache_key("Сколько стоит стекло?", kb.version, ["other-model"], {})
    assert a == b and len({a, c, d}) == 3


def test_tools_never_reserve_or_run_forbidden_effects(kb, mappings):
    from glassflow.modules.intelligence.assistant.tools import TOOLS

    assert {tool.effect for tool in TOOLS.values()} <= {"read", "draft_quote", "draft_task", "job", "none"}
    forbidden = {"sql", "shell", "http", "send", "pay", "reserve", "confirm", "consume", "email", "whatsapp"}
    assert not any(any(word in name for word in forbidden) for name in TOOLS)
    ctx = ToolContext(kb, mappings, "ds")
    assert execute_tool(ctx, "find_remnants", {"catalog_product_id": "steklo-6-prozrachnoe", "length_mm": 450, "width_mm": 370}).result["status"] == "service_unavailable"
    assert execute_tool(ctx, "rank_followups", {}).status == "unavailable"


def test_env_profile_defaults_free_only_without_keys():
    prof = profile_from_env(env={})
    assert prof.mode == "free_only" and prof.primary is None and prof.budget_usd == Decimal("0")
    runtime = build_runtime(prof, _Secrets({}), prompt_version="t")
    assert runtime.status == "disabled" and not runtime.available
    with_key = profile_from_env(env={"GEMINI_API_KEY": "x" * 20})
    assert with_key.primary.model_id == "gemini-3.8-flash" and with_key.fallbacks[0].model_id == "gemini-3.5-flash-lite"
    assert validate_profile(with_key) == []


class _Secrets:
    def __init__(self, data):
        self.data = data

    def get(self, name):
        return self.data.get(name)

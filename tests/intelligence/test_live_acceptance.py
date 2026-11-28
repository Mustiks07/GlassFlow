"""Review F4: live acceptance requires confirmed calls of the selected model (no network here)."""

import asyncio
import json
import sys

import pytest

from glassflow.modules.intelligence.evaluation import __main__ as cli
from glassflow.modules.intelligence.evaluation.live import acceptance, evaluate_live
from glassflow.modules.intelligence.providers.base import ProviderError
from glassflow.modules.intelligence.providers.gateway_client import GatewayProvider
from glassflow.modules.intelligence.providers.gemini import GeminiProvider
from glassflow.modules.intelligence.providers.openrouter import OpenRouterProvider
from glassflow.modules.intelligence.providers.policy import AIProfile, MemoryLedger, ModelRef, ResilientClient
from glassflow.modules.intelligence.providers.settings import AIRuntime

from .conftest import PACK
from .fakes import ScriptedProvider, reply, tool_call


@pytest.fixture()
def no_network(monkeypatch):
    calls = []

    async def forbidden(self, request):
        calls.append(type(self).__name__)
        raise AssertionError("no provider request may be made in this test")

    for cls in (GatewayProvider, GeminiProvider, OpenRouterProvider):
        monkeypatch.setattr(cls, "generate", forbidden)
    return calls


@pytest.mark.parametrize("argv", [["live"], ["live", "--model", "judge_gateway:gateway-pinned"], ["live-open"]])
def test_disabled_profile_with_fake_token_is_blocked_not_success(monkeypatch, tmp_path, no_network, argv):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GLASSFLOW_AI_PROVIDER", "none")
    monkeypatch.setenv("GLASSFLOW_GATEWAY_TOKEN", "fake-token-not-a-secret")
    monkeypatch.setattr(sys, "argv", ["eval", *argv, "--out", str(tmp_path)])
    with pytest.raises(SystemExit) as info:
        cli.main()
    assert info.value.code == 2
    status = json.loads((tmp_path / "live" / "live_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "BLOCKED"
    assert no_network == []


def _runtime(script, model="gemini-3.5-flash-lite"):
    profile = AIProfile(primary=ModelRef(provider="gemini", model_id=model), backoff_base_s=0.01, rpm=None, tpm=None)
    provider = ScriptedProvider(script, model_id=model)
    ledger = MemoryLedger()
    client = ResilientClient(profile=profile, providers={f"gemini:{model}": provider}, ledger=ledger, prompt_version="t",
                             sleep=lambda s: asyncio.sleep(0))
    return (profile, AIRuntime(profile, client, "available", None, {"gemini": True}), ledger), provider


GOOD_E026 = [
    reply(tool_call("calculate_quote", {"catalog_product_id": "steklo-6-prozrachnoe", "length_mm": 450, "width_mm": 370,
                                        "processing": "euro_edge", "edge_sides": "all"}), model="gemini-3.5-flash-lite"),
    reply(tool_call("submit_answer", {"answer_ru": "Стекло 6 мм прозрачное 450×370 мм — 1 332 ₸, евро-кромка — 656 ₸, итого 1 988 ₸."}),
          model="gemini-3.5-flash-lite"),
]


def test_live_pass_requires_answers_from_the_selected_model(tmp_path):
    override, provider = _runtime(list(GOOD_E026))
    report = evaluate_live(PACK, tmp_path, model=None, case_ids=["E026"], runtime_override=override, run_preflight=False)
    assert report["acceptance"]["status"] == "PASS"
    assert report["paths"]["llm_tools"] == 1 and report["paths"]["cache_hits"] == 0
    assert report["model_call_latency_ms"]["n"] == 2 and len(provider.requests) == 2


def test_live_with_only_deterministic_fallbacks_is_blocked(tmp_path):
    override, _ = _runtime([ProviderError("unavailable", "down")] * 10)
    report = evaluate_live(PACK, tmp_path, model=None, case_ids=["E026", "E053"], runtime_override=override, run_preflight=False)
    assert report["acceptance"]["status"] == "BLOCKED"
    assert report["paths"]["llm_tools"] == 0 and report["model_call_latency_ms"]["n"] == 0


def test_live_partial_and_fail_are_not_pass():
    online_ok = {"answer_path": "llm_tools", "selected_model": True, "cache_hit": False, "ok": True}
    fallback = {"answer_path": "fallback", "selected_model": False, "cache_hit": False, "ok": True}
    wrong = {**online_ok, "ok": False}
    assert acceptance([online_ok, fallback], ok_calls=2, unsupported_shown=0)["status"] == "PARTIAL"
    assert acceptance([online_ok, wrong], ok_calls=2, unsupported_shown=0)["status"] == "FAIL"
    assert acceptance([online_ok], ok_calls=1, unsupported_shown=1)["status"] == "FAIL"
    assert acceptance([{**online_ok, "cache_hit": True}], ok_calls=1, unsupported_shown=0)["status"] == "BLOCKED"
    assert acceptance([online_ok], ok_calls=0, unsupported_shown=0)["status"] == "BLOCKED"


def test_hybrid_extended_run_is_labelled_not_live(tmp_path):
    from glassflow.modules.intelligence.evaluation.runner import evaluate_extended

    report = evaluate_extended(PACK, tmp_path, allow_ai=True)
    assert report["live_acceptance"].startswith("not_applicable")
    assert set(report["answer_paths"]) <= {"deterministic", "llm_tools", "fallback"}


def test_live_waits_out_a_short_cooldown_instead_of_burning_cases(tmp_path):
    """A per-minute 429 opens the breaker; the evaluator waits it out before the next case."""
    limited = [ProviderError("rate_limit", "per-minute limit", retry_after_s=5)] * 3
    override, _ = _runtime(limited + list(GOOD_E026))
    client = override[1].client
    waits = []

    def fake_sleep(seconds):
        waits.append(seconds)
        client.unhealthy_until.clear()  # the cooldown has passed

    report = evaluate_live(PACK, tmp_path, model=None, case_ids=["E026"], repeats=2, runtime_override=override,
                           run_preflight=False, sleep=fake_sleep)
    assert len(waits) == 1 and 0 < waits[0] <= 90
    assert report["paths"]["fallback"] == 1 and report["paths"]["llm_tools"] == 1
    assert report["pacing"]["waits_s"] and report["stopped_early"] is None
    assert report["acceptance"]["status"] == "PARTIAL"


def test_live_stops_on_daily_quota_and_reports_cases_as_not_run(tmp_path):
    daily = [ProviderError("rate_limit", "GenerateRequestsPerDayPerProjectPerModel-FreeTier", retry_after_s=37000)]
    override, provider = _runtime(daily * 3)
    slept = []
    report = evaluate_live(PACK, tmp_path, model=None, case_ids=["E026"], repeats=3, runtime_override=override,
                           run_preflight=False, sleep=slept.append)
    assert slept == [] and len(provider.requests) == 1  # no waiting for hours, no further quota spent
    assert report["planned_runs"] == 3 and report["runs"] == 1 and "unavailable" in report["stopped_early"]
    acc = report["acceptance"]
    assert acc["status"] == "BLOCKED" and acc["not_run"] == 2 and any("PerDay" in r for r in acc["reasons"])


def test_not_run_cases_prevent_pass():
    online_ok = {"answer_path": "llm_tools", "selected_model": True, "cache_hit": False, "ok": True}
    result = acceptance([online_ok], ok_calls=1, unsupported_shown=0, not_run=5, stop_reason="daily quota")
    assert result["status"] == "PARTIAL" and result["not_run"] == 5


def test_verifier_rejected_model_answer_counts_as_failed_online_run():
    online_ok = {"answer_path": "llm_tools", "selected_model": True, "cache_hit": False, "ok": True}
    rejected = {"answer_path": "fallback", "selected_model": False, "cache_hit": False, "ok": True,
                "llm_status": "verifier_rejected", "model_answered": True}
    result = acceptance([online_ok, rejected], ok_calls=4, unsupported_shown=0)
    assert result["status"] == "FAIL" and result["online_runs"] == 2 and result["online_ok"] == 1
    assert result["verifier_rejected_model_answers"] == 1

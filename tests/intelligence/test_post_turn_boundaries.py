"""Authorized warmup defects, reproduced without provider/network access."""

import asyncio
import time

import pytest

from glassflow.modules.intelligence.assistant.engine import AssistantEngine
from glassflow.modules.intelligence.providers.base import ProviderError, ProviderRequest
from glassflow.modules.intelligence.providers.policy import MemoryLedger, ResilientClient, capture_attempts

from .fakes import ScriptedProvider, reply, tool_call
from .test_ai_resilience import profile, runtime_with
from .test_api import app_client as _app_client
from .test_post_provenance import call, set_runtime

app_client = _app_client
COMPLETE = "Стекло 6 мм прозрачное 450×370 мм, 1 шт., без обработки"


def quote_step():
    return reply(tool_call("calculate_quote", {"catalog_product_id": "steklo-6-prozrachnoe",
                 "length_mm": 450, "width_mm": 370, "quantity": 1, "processing": "none"}))


def test_http_timeout_has_no_unadvertised_one_second_grace():
    class Slow(ScriptedProvider):
        async def generate(self, request):
            self.requests.append(request)
            await asyncio.sleep(.4)
            return reply(text="too late")
    provider = Slow([])
    prof = profile(fallbacks=[], request_timeout_s=.05, max_retries=0)
    client = ResilientClient(prof, {prof.primary.label: provider}, MemoryLedger(), "test")
    started = time.monotonic()
    with pytest.raises(ProviderError) as info:
        asyncio.run(client.call(ProviderRequest("test", []), deadline=time.monotonic() + 5))
    assert info.value.kind == "timeout"
    assert time.monotonic() - started < .25
    assert len(provider.requests) == 1


def test_semaphore_queue_is_bounded_and_does_not_count_an_unsent_http_call():
    provider = ScriptedProvider([reply(text="must not be sent")])
    prof = profile(fallbacks=[], max_concurrency=1, max_retries=0)
    client = ResilientClient(prof, {prof.primary.label: provider}, MemoryLedger(), "test")
    async def run():
        await client.limiter.semaphore.acquire()
        attempts = []
        started = time.monotonic()
        try:
            with capture_attempts(attempts), pytest.raises(ProviderError) as info:
                await asyncio.wait_for(client.call(ProviderRequest("test", []), deadline=time.monotonic() + 2.1), 3)
            assert info.value.kind == "timeout"
            assert time.monotonic() - started < 2.7
            assert attempts == [] and provider.requests == []
        finally:
            client.limiter.semaphore.release()
    asyncio.run(run())


def test_whole_turn_budget_covers_multiple_model_calls_and_cancellation_is_traced(kb, mappings):
    class TwoSteps(ScriptedProvider):
        async def generate(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                await asyncio.sleep(.05)
                return quote_step()
            await asyncio.sleep(5)
    provider = TwoSteps([])
    prof = profile(fallbacks=[], turn_deadline_s=2.5, request_timeout_s=5, max_retries=0)
    runtime = runtime_with({prof.primary.label: provider}, prof)
    engine = AssistantEngine(kb, mappings, dataset_id="ds", runtime=runtime)
    started = time.monotonic()
    result = asyncio.run(engine.turn(COMPLETE, strategy="ai_first", inventory_mode="none"))
    assert time.monotonic() - started < 3
    assert result.answer_path == "fallback" and result.provider is None
    assert result.ai_unavailable_reason and result.llm.error.kind == "timeout"
    assert len(result.model_attempts) == 2 and result.model_attempts[-1]["status"] == "error"
    assert provider.requests[-1].timeout_s < 2.5


def test_unbound_literal_still_rejects_and_now_explains_fallback(app_client):
    set_runtime(app_client, [quote_step(), reply(tool_call("submit_answer", {
        "answer_ru": "[[quote]] Итого 1332,00 ₸.", "needs_manager": False}))])
    result = call(app_client, COMPLETE, execution_mode="model_first").json()
    assert result["origin"] == "fallback" and result["verifier_reject_count"] == 1
    assert result["ai_unavailable_reason"] and result["provider"] is None
    assert result["quote"]["total_tg"] == "1332.00"


def test_wrong_model_handoff_flag_is_rejected_not_relabelled_as_a_success(app_client):
    set_runtime(app_client, [quote_step(), reply(tool_call("submit_answer", {
        "answer_ru": "[[quote]] Предварительную стоимость подтверждает менеджер.", "needs_manager": True}))])
    result = call(app_client, COMPLETE, execution_mode="model_first").json()
    assert result["origin"] == "fallback" and result["status"] == "answered"
    assert result["verifier_reject_count"] == 1 and result["model_call_count"] == 2
    assert result["provider"] is None and result["card"]["needs_manager"] is False
    assert result["ai_unavailable_reason"]


def test_complete_model_quote_with_consistent_flag_is_accepted(app_client):
    set_runtime(app_client, [quote_step(), reply(tool_call("submit_answer", {
        "answer_ru": "[[quote]] Предварительную стоимость подтверждает менеджер.", "needs_manager": False}))])
    result = call(app_client, COMPLETE, execution_mode="model_first").json()
    assert result["origin"] == "model" and result["status"] == "answered"
    assert result["card"]["needs_manager"] is False and result["verifier_reject_count"] == 0


def test_known_manager_policy_handoff_remains_an_accepted_model_response(app_client):
    set_runtime(app_client, [reply(tool_call("get_rules", {"topic": "delivery"})),
        reply(tool_call("submit_answer", {"answer_ru": "Оплату и доставку согласует менеджер.", "needs_manager": True}))])
    result = call(app_client, "Как согласовать доставку?", execution_mode="model_first").json()
    assert result["origin"] == "model" and result["status"] == "manager_handoff"
    assert result["quote"] is None and result["verifier_reject_count"] == 0


def test_manager_priced_policy_does_not_repeat_questions_that_cannot_unlock_a_rate(app_client):
    set_runtime(app_client, [reply(tool_call("get_rules", {"topic": "mirror_models"})),
        reply(tool_call("submit_answer", {"answer_ru": "Цену этой модели рассчитает менеджер. Уточните размеры.",
                                         "clarification": "Какие размеры нужны?", "needs_manager": True}))])
    result = call(app_client, "Сколько стоит зеркало AB1020 размером 600×400 мм?", execution_mode="model_first").json()
    assert result["origin"] == "fallback" and result["status"] == "manager_handoff"
    assert result["clarification"] is None and result["quote"] is None
    assert result["verifier_reject_count"] == 1 and result["ai_unavailable_reason"]


def test_profile_exposes_actual_runtime_timeouts(app_client):
    set_runtime(app_client, [], request_timeout_s=17, turn_deadline_s=61)
    response = app_client.get("/api/v1/assistant/ai-status")
    assert response.status_code == 200
    result = response.json()
    assert result["request_timeout_s"] == 17 and result["turn_deadline_s"] == 61

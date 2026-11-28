from glassflow.modules.intelligence.providers.base import ProviderError

from .fakes import ScriptedProvider, reply, tool_call
from .test_ai_resilience import profile, runtime_with
from .test_api import app_client as _app_client
from .test_api import kb_version

app_client = _app_client


def call(client, text="Нужно что-то красивое для кухни", **kwargs):
    return client.post("/api/v1/assistant/turns", json={
        "dataset_id": "ds-a", "kb_version": kb_version(client), "text": text, "inventory_mode": "none", **kwargs,
    })


def script_answer():
    return reply(tool_call("submit_answer", {"answer_ru": "Уточните, пожалуйста, нужный материал.",
                                             "clarification": "Какой материал нужен?"}))


def set_runtime(client, script, **kwargs):
    provider = ScriptedProvider(script)
    runtime = runtime_with({"gemini:gemini-3.8-flash": provider}, profile(fallbacks=[], **kwargs))
    client.app.state.intelligence_service.runtime = runtime
    return provider


def test_model_first_unconfigured_is_explicit_fallback_and_contradiction_is_422(app_client):
    result = call(app_client, execution_mode="model_first").json()
    assert result["origin"] == "fallback" and result["model_call_count"] == 0
    assert result["model_attempts"] == [] and result["ai_unavailable_reason"]
    assert result["mode"] == "local_limited" and result["provider"] is None
    assert call(app_client, execution_mode="model_first", allow_ai=False).status_code == 422


def test_hybrid_cache_and_model_first_bypass_report_distinct_provenance(app_client):
    provider = set_runtime(app_client, [script_answer(), script_answer(), script_answer()])
    first = call(app_client).json()
    assert first["origin"] == "model" and first["model_call_count"] == 1
    assert first["selected_provider"] == "gemini" and first["selected_model_id"] == "gemini-3.8-flash"
    cached = call(app_client).json()
    assert cached["origin"] == "cache" and cached["cache_hit"] is True
    assert cached["model_call_count"] == 0 and cached["model_attempts"] == []
    forced = call(app_client, execution_mode="model_first").json()
    assert forced["origin"] == "model" and forced["cache_hit"] is False
    assert forced["model_call_count"] == 1 and len(provider.requests) == 2


def test_failed_http_attempts_and_retries_are_counted(app_client):
    set_runtime(app_client, [ProviderError("server", "mock down"), script_answer()], max_retries=1)
    result = call(app_client, execution_mode="model_first").json()
    assert result["origin"] == "model" and result["model_call_count"] == 2
    assert [item["status"] for item in result["model_attempts"]] == ["error", "ok"]
    assert result["model_attempts"][0]["error_kind"] == "server"


def test_provider_failure_is_not_claimed_as_model_answer(app_client):
    set_runtime(app_client, [ProviderError("auth", "mock unauthorized")], max_retries=0)
    result = call(app_client, execution_mode="model_first").json()
    assert result["origin"] == "fallback" and result["model_call_count"] == 1
    assert result["provider"] is None and result["model_id"] is None
    assert result["model_attempts"][0]["error_kind"] == "auth"


def test_model_cannot_bypass_local_mandatory_product_choice(app_client):
    set_runtime(app_client, [reply(tool_call("calculate_quote", {
        "catalog_product_id": "sensor-dvoynoy-yzkj-f2ftc", "quantity": 3})),
        reply(tool_call("submit_answer", {"answer_ru": "[[quote]]"}))])
    result = call(app_client, "Нужен сенсорный переключатель для зеркала, сколько за 3 шт?", execution_mode="model_first").json()
    assert result["origin"] == "fallback" and result["quote"] is None
    assert result["status"] == "clarification" and result["verifier_reject_count"] == 1

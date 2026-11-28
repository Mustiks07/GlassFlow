"""MockTransport only: real service spending is owned by the integrator."""

import asyncio
import json
import time

import httpx
import pytest

from glassflow.modules.intelligence.providers.base import ChatMessage, ProviderError, ProviderRequest
from glassflow.modules.intelligence.providers.basisweb import (
    API_URL,
    BasisWebProvider,
    reserve_quota,
    usage_quota,
)
from glassflow.modules.intelligence.providers.policy import (
    AIProfile,
    MemoryLedger,
    ModelRef,
    ResilientClient,
    capture_attempts,
    validate_profile,
)
from glassflow.modules.intelligence.providers.settings import EnvSecrets, build_runtime, profile_from_env


def profile(**kwargs):
    return AIProfile(primary=ModelRef(provider="basisweb", model_id="gpt-6-luna"), included_quota_enabled=True,
                     max_retries=0, max_concurrency=1, max_output_tokens=256, **kwargs)


def response(usage=True):
    return {"id": "test-response", "model": "gpt-6-luna", "choices": [
        {"message": {"content": "OK"}, "finish_reason": "stop"}],
        **({"usage": {"prompt_tokens": 100, "completion_tokens": 10,
                      "prompt_tokens_details": {"cached_tokens": 20},
                      "completion_tokens_details": {"reasoning_tokens": 5}}} if usage else {})}


def test_host_redirect_and_actual_model_are_pinned():
    for url in ["http://api.basisweb.ru/v1/chat/completions", "https://evil.invalid/v1/chat/completions",
                "https://api.basisweb.ru.evil.invalid/v1/chat/completions", API_URL + "?redirect=1"]:
        with pytest.raises(ValueError):
            BasisWebProvider("gpt-6-luna", "test-not-secret", base_url=url)
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.invalid/"})
    provider = BasisWebProvider("gpt-6-luna", "test-not-secret", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="BasisWeb 302"):
        asyncio.run(provider.generate(ProviderRequest("test", [])))
    assert len(seen) == 1
    altered = response()
    altered["model"] = "different-model"
    provider = BasisWebProvider("gpt-6-luna", "test-not-secret", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=altered)))
    with pytest.raises(ProviderError, match="подмена"):
        asyncio.run(provider.generate(ProviderRequest("test", [])))


def test_openai_tools_usage_and_honest_provider():
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=response())
    provider = BasisWebProvider("gpt-6-luna", "test-not-secret", transport=httpx.MockTransport(handler))
    result = asyncio.run(provider.generate(ProviderRequest("test", [ChatMessage("user", "hello")], max_output_tokens=256)))
    assert result.provider == "basisweb" and result.model_id == "gpt-6-luna"
    assert result.usage.cost_usd is None
    assert usage_quota(result.usage, result.model_id) == 132  # reasoning is already within completion_tokens
    assert seen[0]["max_tokens"] == 256
    assert "provider" not in seen[0] and "usage" not in seen[0]  # no OpenRouter-only extensions


def test_explicit_opt_in_and_unknown_rates_are_rejected_before_network():
    ref = ModelRef(provider="basisweb", model_id="gpt-6-luna")
    assert validate_profile(AIProfile(primary=ref))
    assert not validate_profile(profile())
    assert validate_profile(profile().model_copy(update={"primary": ref.model_copy(update={"model_id": "unknown"})}))
    default = profile_from_env({"BASISWEB_API_KEY": "test-not-secret"})
    assert default.primary is None  # never implicitly selected by key presence
    explicit = profile_from_env({"GLASSFLOW_AI_PROVIDER": "basisweb", "GLASSFLOW_AI_INCLUDED_QUOTA_ENABLED": "true"})
    assert explicit.primary.provider == "basisweb" and explicit.max_concurrency == 1 and explicit.max_output_tokens == 512
    runtime = build_runtime(AIProfile(primary=ref), EnvSecrets({"BASISWEB_API_KEY": "test-not-secret"}), prompt_version="test")
    assert runtime.status == "invalid_profile"


@pytest.mark.parametrize("failure", [False, True])
def test_missing_usage_and_failures_keep_reservation_and_cap_prevents_next_http(failure):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(500 if failure else 200, json={"error": "failed"} if failure else response(usage=False))
    request = ProviderRequest("test", [ChatMessage("user", "Привет")], max_output_tokens=256)
    reservation = reserve_quota(request, "gpt-6-luna")
    client = ResilientClient(profile(quota_token_budget=reservation),
                             {"basisweb:gpt-6-luna": BasisWebProvider("gpt-6-luna", "test-not-secret", transport=httpx.MockTransport(handler))},
                             MemoryLedger(), "test")
    async def run():
        attempts = []
        with capture_attempts(attempts):
            try:
                await client.call(request, deadline=time.monotonic() + 5)
            except ProviderError:
                assert failure
        assert len(attempts) == 1
        assert client.quota_tokens_spent == reservation
        with pytest.raises(ProviderError):
            await client.call(request, deadline=time.monotonic() + 5)
    asyncio.run(run())
    assert len(calls) == 1


def test_error_messages_redact_credentials():
    provider = BasisWebProvider("gpt-6-luna", "test-not-secret", transport=httpx.MockTransport(
        lambda r: httpx.Response(401, json={"error": {"message": "bad test-not-secret"}})))
    with pytest.raises(ProviderError) as info:
        asyncio.run(provider.generate(ProviderRequest("test", [])))
    assert "test-not-secret" not in str(info.value)

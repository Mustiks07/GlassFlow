"""Adapter contract tests with fake transports (no network, no keys).

These verify request/response mapping and error classification only. A live provider check
is a separate, explicitly recorded run (docs/ai/EVALUATION.md); it is not replaced by these.
"""

import asyncio
import json

import httpx
import pytest

from glassflow.modules.intelligence.providers.base import (
    ChatMessage,
    ProviderError,
    ProviderRequest,
    ToolCall,
    ToolSpec,
)
from glassflow.modules.intelligence.providers.gateway_client import GatewayProvider
from glassflow.modules.intelligence.providers.gemini import GeminiProvider
from glassflow.modules.intelligence.providers.openrouter import OpenRouterProvider

SECRET = "sk-or-test-secret-123456"


def request(**kwargs) -> ProviderRequest:
    data = dict(
        system="sys",
        messages=[
            ChatMessage(role="user", text="hi"),
            ChatMessage(role="assistant", tool_calls=[ToolCall("c1", "search_catalog", '{"query":"x"}', {"query": "x"})]),
            ChatMessage(role="tool", text='{"status":"exact"}', tool_call_id="c1", tool_name="search_catalog"),
        ],
        tools=[ToolSpec("search_catalog", "d", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})],
    )
    data.update(kwargs)
    return ProviderRequest(**data)


def test_openrouter_maps_tools_usage_and_disables_internal_fallbacks():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "id": "gen-1",
                "model": "google/gemma-4-31b-it:free",
                "choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
                    {"id": "t1", "type": "function", "function": {"name": "calculate_quote", "arguments": '{"catalog_product_id":"steklo-6-prozrachnoe"}'}}
                ]}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 7, "cost": 0},
            },
        )

    provider = OpenRouterProvider("google/gemma-4-31b-it:free", SECRET, transport=httpx.MockTransport(handler))
    response = asyncio.run(provider.generate(request()))
    body = seen["body"]
    assert body["model"] == "google/gemma-4-31b-it:free"
    assert body["provider"] == {"allow_fallbacks": False}
    assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "tool"]
    assert body["messages"][2]["tool_calls"][0]["function"]["name"] == "search_catalog"
    assert response.tool_calls[0].arguments == {"catalog_product_id": "steklo-6-prozrachnoe"}
    assert response.usage.input_tokens == 50 and str(response.usage.cost_usd) == "0"
    assert response.model_id == "google/gemma-4-31b-it:free"


@pytest.mark.parametrize(
    ("status", "headers", "kind", "retry_after"),
    [(401, {}, "auth", None), (403, {}, "auth", None), (402, {}, "budget", None), (429, {"retry-after": "7"}, "rate_limit", 7.0),
     (503, {}, "server", None), (400, {}, "bad_request", None)],
)
def test_openrouter_error_classification_without_secret_leak(status, headers, kind, retry_after):
    def handler(req):
        return httpx.Response(status, headers=headers, json={"error": {"code": status, "message": f"bad key {SECRET}"}})

    provider = OpenRouterProvider("google/gemma-4-31b-it:free", SECRET, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as info:
        asyncio.run(provider.generate(request()))
    assert info.value.kind == kind and info.value.retry_after_s == retry_after
    assert SECRET not in str(info.value)


def test_openrouter_malformed_tool_arguments_are_kept_raw():
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"id": "t", "function": {"name": "calculate_quote", "arguments": "{broken"}}]}}]})

    provider = OpenRouterProvider("m:free", SECRET, transport=httpx.MockTransport(handler))
    response = asyncio.run(provider.generate(request()))
    assert response.tool_calls[0].arguments is None and response.tool_calls[0].arguments_json == "{broken"
    assert response.usage.cost_usd is None  # unknown, not zero


def test_openrouter_timeout_maps_to_timeout():
    def handler(req):
        raise httpx.ReadTimeout("slow")

    provider = OpenRouterProvider("m:free", SECRET, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as info:
        asyncio.run(provider.generate(request()))
    assert info.value.kind == "timeout"


class _FakeModels:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    async def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        if self.error:
            raise self.error
        return self.result


class _FakeClient:
    def __init__(self, models):
        self.aio = type("Aio", (), {"models": models})()


def test_gemini_maps_function_calls_usage_and_keeps_signature_state():
    from google.genai import types

    content = types.Content(
        role="model",
        parts=[types.Part(function_call=types.FunctionCall(id="f1", name="calculate_quote", args={"catalog_product_id": "x"}),
                          thought_signature=b"sig")],
    )
    result = types.GenerateContentResponse(
        candidates=[types.Candidate(content=content, finish_reason="STOP")],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=40, candidates_token_count=9, thoughts_token_count=3),
        model_version="gemini-3.8-flash",
    )
    models = _FakeModels(result=result)
    provider = GeminiProvider("gemini-3.8-flash", "AIza-test-key-0000", client=_FakeClient(models))
    response = asyncio.run(provider.generate(request()))
    model, contents, config = models.calls[0]
    assert model == "gemini-3.8-flash"
    assert config.automatic_function_calling.disable is True
    assert config.system_instruction == "sys"
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[2].parts[0].function_response.name == "search_catalog"
    assert response.tool_calls[0].name == "calculate_quote" and response.tool_calls[0].arguments == {"catalog_product_id": "x"}
    assert (response.usage.input_tokens, response.usage.output_tokens, response.usage.thought_tokens) == (40, 9, 3)
    assert response.usage.cost_usd is None
    # replaying the stored model turn keeps the thought signature
    replay = ChatMessage(role="assistant", tool_calls=response.tool_calls, provider_state=response.provider_state)
    rebuilt = provider._contents([ChatMessage(role="user", text="hi"), replay])
    assert rebuilt[1].parts[0].thought_signature == b"sig"


@pytest.mark.parametrize(("code", "kind"), [(401, "auth"), (403, "auth"), (429, "rate_limit"), (500, "server"), (404, "bad_request")])
def test_gemini_error_mapping(code, kind):
    from google.genai import errors

    details = {"error": {"code": code, "message": "x AIza-test-key-0000", "status": "S",
                         "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12s"}]}}
    error = errors.ClientError(code, details) if code < 500 else errors.ServerError(code, details)
    provider = GeminiProvider("gemini-3.8-flash", "AIza-test-key-0000", client=_FakeClient(_FakeModels(error=error)))
    with pytest.raises(ProviderError) as info:
        asyncio.run(provider.generate(request()))
    assert info.value.kind == kind
    assert "AIza-test-key-0000" not in str(info.value)
    if kind == "rate_limit":
        assert info.value.retry_after_s == 12.0


def test_gateway_client_sends_no_system_prompt_or_model():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json={"provider": "gemini", "model_id": "gemini-3.8-flash", "text": "ok", "tool_calls": [],
                                         "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": None}})

    provider = GatewayProvider("https://gw.example", "tok-123456", prompt_version="v1", session_id="s", transport=httpx.MockTransport(handler))
    response = asyncio.run(provider.generate(request()))
    assert set(seen["body"]) == {"session_id", "prompt_version", "purpose", "messages"}
    assert "system" not in json.dumps(seen["body"]) or seen["body"]["messages"][0]["role"] == "user"
    assert response.model_id == "gemini-3.8-flash" and response.provider == "judge_gateway/gemini"
    with pytest.raises(ValueError):
        GatewayProvider("http://gw.example", "t", prompt_version="v1", session_id="s")


def test_gemini_invalid_key_400_is_auth():
    from google.genai import errors

    details = {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "API key not valid. Please pass a valid API key.",
                         "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]}}
    provider = GeminiProvider("gemini-3.5-flash-lite", "AIza-test-key-0000", client=_FakeClient(_FakeModels(error=errors.ClientError(400, details))))
    with pytest.raises(ProviderError) as info:
        asyncio.run(provider.generate(request()))
    assert info.value.kind == "auth" and not info.value.retryable

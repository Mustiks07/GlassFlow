"""Gemini adapter on the official google-genai SDK.

The SDK's own retries and automatic function calling are disabled: retries, quotas and tool
execution belong to ResilientClient and the local tool registry. Model turns are replayed
verbatim from ``provider_state`` so thought signatures survive multi-step tool calls.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from .base import ChatMessage, ProviderError, ProviderRequest, ProviderResponse, ToolCall, Usage, sanitize


def _retry_after(details: Any, response: Any) -> float | None:
    try:
        header = response.headers.get("retry-after") if response is not None else None
        if header:
            return float(header)
    except (AttributeError, ValueError, TypeError):
        pass
    try:
        for item in (details or {}).get("error", {}).get("details", []):
            delay = item.get("retryDelay")
            if delay:
                match = re.match(r"([\d.]+)s", delay)
                if match:
                    return float(match.group(1))
    except AttributeError:
        return None
    return None


class GeminiProvider:
    name = "gemini"

    def __init__(self, model_id: str, api_key: str, *, client: Any | None = None):
        self.model_id = model_id
        self._api_key = api_key
        self._client = client

    def capabilities(self) -> dict[str, bool]:
        return {"tools": True, "structured_output": True, "thought_signatures": True, "usage": True}

    def _sdk(self):
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
            )
        return self._client

    def _contents(self, messages: list[ChatMessage]):
        from google.genai import types

        contents = []
        pending_tool_parts = []
        for message in messages:
            if message.role == "tool":
                try:
                    payload = json.loads(message.text or "{}")
                except json.JSONDecodeError:
                    payload = {"result": message.text}
                if not isinstance(payload, dict):
                    payload = {"result": payload}
                pending_tool_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=message.tool_name or "tool", response=payload, id=message.tool_call_id
                        )
                    )
                )
                continue
            if pending_tool_parts:
                contents.append(types.Content(role="user", parts=pending_tool_parts))
                pending_tool_parts = []
            if message.role == "assistant":
                if message.provider_state and message.provider_state.get("gemini_content"):
                    contents.append(types.Content.model_validate(message.provider_state["gemini_content"]))
                    continue
                parts = []
                if message.text:
                    parts.append(types.Part(text=message.text))
                for call in message.tool_calls:
                    parts.append(
                        types.Part(function_call=types.FunctionCall(id=call.call_id, name=call.name, args=call.arguments or {}))
                    )
                contents.append(types.Content(role="model", parts=parts))
            else:
                contents.append(types.Content(role="user", parts=[types.Part(text=message.text or "")]))
        if pending_tool_parts:
            contents.append(types.Content(role="user", parts=pending_tool_parts))
        return contents

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        from google.genai import errors, types

        client = self._sdk()
        tools = None
        tool_config = None
        if request.tools:
            tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=tool.name, description=tool.description, parameters_json_schema=tool.parameters
                        )
                        for tool in request.tools
                    ]
                )
            ]
            tool_config = types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="AUTO"))
        config = types.GenerateContentConfig(
            system_instruction=request.system,
            tools=tools,
            tool_config=tool_config,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=request.max_output_tokens,
            temperature=request.temperature,
            http_options=types.HttpOptions(timeout=int(request.timeout_s * 1000)),
        )
        started = time.monotonic()
        try:
            response = await client.aio.models.generate_content(
                model=self.model_id, contents=self._contents(request.messages), config=config
            )
        except errors.APIError as exc:
            code = getattr(exc, "code", None) or 0
            message = sanitize(str(getattr(exc, "message", "") or exc), [self._api_key])
            if code in (401, 403):
                raise ProviderError("auth", f"Gemini: нет доступа ({code}). {message}", status=code, provider=self.name, model_id=self.model_id) from None
            if code == 429:
                raise ProviderError(
                    "rate_limit", f"Gemini: квота исчерпана (429). {message}", status=code,
                    retry_after_s=_retry_after(getattr(exc, "details", None), getattr(exc, "response", None)),
                    provider=self.name, model_id=self.model_id,
                ) from None
            if code >= 500:
                raise ProviderError("server", f"Gemini: ошибка сервиса ({code}).", status=code, provider=self.name, model_id=self.model_id) from None
            raise ProviderError("bad_request", f"Gemini: запрос отклонен ({code}). {message}", status=code, provider=self.name, model_id=self.model_id) from None
        except TimeoutError:
            raise ProviderError("timeout", "Gemini: тайм-аут.", provider=self.name, model_id=self.model_id) from None
        except Exception as exc:
            name = type(exc).__name__
            kind = "timeout" if "Timeout" in name else "unavailable"
            raise ProviderError(kind, f"Gemini: сбой соединения ({name}).", provider=self.name, model_id=self.model_id) from None
        latency = int((time.monotonic() - started) * 1000)
        candidates = response.candidates or []
        if not candidates or candidates[0].content is None:
            reason = str(candidates[0].finish_reason) if candidates else "no_candidates"
            raise ProviderError("malformed", f"Gemini: пустой ответ ({reason}).", provider=self.name, model_id=self.model_id)
        content = candidates[0].content
        texts: list[str] = []
        calls: list[ToolCall] = []
        for part in content.parts or []:
            if getattr(part, "thought", False):
                continue
            if part.function_call is not None:
                args = dict(part.function_call.args or {})
                calls.append(
                    ToolCall(
                        call_id=part.function_call.id or f"call-{uuid.uuid4().hex[:8]}",
                        name=part.function_call.name or "",
                        arguments_json=json.dumps(args, ensure_ascii=False),
                        arguments=args,
                    )
                )
            elif part.text:
                texts.append(part.text)
        meta = response.usage_metadata
        usage = Usage(
            input_tokens=getattr(meta, "prompt_token_count", None),
            output_tokens=getattr(meta, "candidates_token_count", None),
            thought_tokens=getattr(meta, "thoughts_token_count", None),
            cached_tokens=getattr(meta, "cached_content_token_count", None),
            cost_usd=None,
            cost_source="not_reported_by_gemini; derive from tokens x dated tariff",
        )
        return ProviderResponse(
            provider=self.name,
            model_id=response.model_version or self.model_id,
            text="\n".join(texts) or None,
            tool_calls=calls,
            usage=usage,
            finish_reason=str(candidates[0].finish_reason) if candidates[0].finish_reason else None,
            latency_ms=latency,
            provider_state={"gemini_content": content.model_dump(mode="json", exclude_none=True)},
            request_id=response.response_id,
        )

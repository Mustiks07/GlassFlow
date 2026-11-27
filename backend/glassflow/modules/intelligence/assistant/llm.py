"""Tool-calling loop for the online AI path.

- at most ``max_tool_iterations`` model calls per turn (default 6) and one overall deadline;
- every tool call is validated locally (unknown tool / malformed JSON / bad args → rejected,
  reported back to the model, counted as a tool error);
- a malformed final answer gets a bounded repair attempt inside the same iteration budget;
- the final text is checked by verify_answer; unsupported claims are not shown.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..providers.base import ChatMessage, ProviderError, ProviderRequest, ToolSpec
from ..providers.policy import ResilientClient
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, USER_TEMPLATE
from .tools import ASSISTANT_TOOLSET, TOOLS, ToolContext, ToolExecution, execute_tool
from .verifier import VerificationResult, verify_answer

MAX_USER_CHARS = 4000  # context minimization: the model never receives more than this per turn


@dataclass
class LlmOutcome:
    status: str  # final | iteration_cap | verifier_rejected | provider_error | empty
    answer: str | None = None
    clarification: str | None = None
    needs_manager: bool = False
    executions: list[ToolExecution] = field(default_factory=list)
    verification: VerificationResult | None = None
    provider: str | None = None
    model_id: str | None = None
    model_calls: int = 0
    tool_errors: int = 0
    error: ProviderError | None = None
    fallback_used: bool = False


def tool_specs(names: list[str] | None = None) -> list[ToolSpec]:
    return [ToolSpec(TOOLS[n].name, TOOLS[n].description, TOOLS[n].parameters) for n in (names or ASSISTANT_TOOLSET)]


def build_user_message(text: str, context: dict[str, str]) -> str:
    safe_context = {k: v for k, v in context.items() if k in {
        "product_id", "length_mm", "width_mm", "quantity", "processing", "edge_sides", "price_basis"
    }}
    bounded = text[:MAX_USER_CHARS].replace(">>>", "> > >")
    return USER_TEMPLATE.format(context=json.dumps(safe_context, ensure_ascii=False), text=bounded)


async def run_llm_turn(
    client: ResilientClient,
    ctx: ToolContext,
    text: str,
    context: dict[str, str],
    *,
    deadline: float,
    max_iterations: int | None = None,
    correlation_id: str | None = None,
    tool_names: list[str] | None = None,
) -> LlmOutcome:
    max_iterations = max_iterations or client.profile.max_tool_iterations
    messages = [ChatMessage(role="user", text=build_user_message(text, context))]
    allowed = tool_names or ASSISTANT_TOOLSET
    specs = tool_specs(allowed)
    outcome = LlmOutcome(status="iteration_cap")
    for iteration in range(max_iterations):
        request = ProviderRequest(
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=specs,
            max_output_tokens=client.profile.max_output_tokens,
            purpose="assistant_turn" if iteration == 0 else "assistant_tool_followup",
        )
        try:
            call = await client.call(request, deadline=deadline, correlation_id=correlation_id)
        except ProviderError as exc:
            outcome.status, outcome.error = "provider_error", exc
            return outcome
        response = call.response
        outcome.model_calls += call.attempts
        outcome.provider, outcome.model_id = response.provider, response.model_id
        outcome.fallback_used = outcome.fallback_used or call.fallback_used
        messages.append(
            ChatMessage(role="assistant", text=response.text, tool_calls=response.tool_calls, provider_state=response.provider_state)
        )
        if not response.tool_calls:
            if response.text and response.text.strip():
                outcome.status, outcome.answer = "final", response.text.strip()
                break
            messages.append(ChatMessage(role="user", text="Пустой ответ. Заверши ход вызовом submit_answer."))
            outcome.tool_errors += 1
            continue
        final_args = None
        for tool_call in response.tool_calls:
            execution = execute_tool(
                ctx, tool_call.name, tool_call.arguments if tool_call.arguments is not None else tool_call.arguments_json, allowed
            )
            outcome.executions.append(execution)
            if execution.status == "rejected":
                outcome.tool_errors += 1
            if tool_call.name == "submit_answer" and execution.status == "ok":
                final_args = execution.arguments
            messages.append(
                ChatMessage(role="tool", text=execution.result_json(), tool_call_id=tool_call.call_id, tool_name=tool_call.name)
            )
        if final_args is not None:
            outcome.status = "final"
            outcome.answer = final_args["answer_ru"].strip()
            outcome.clarification = final_args.get("clarification")
            outcome.needs_manager = bool(final_args.get("needs_manager"))
            break
    if outcome.status != "final" or not outcome.answer:
        if outcome.status == "final":
            outcome.status = "empty"
        return outcome
    outcome.verification = verify_answer(outcome.answer, ctx.facts, text, remnant_checked=ctx.remnant_checked)
    if outcome.verification.status != "supported":
        outcome.status = "verifier_rejected"
    return outcome


__all__ = ["LlmOutcome", "PROMPT_VERSION", "run_llm_turn", "tool_specs"]

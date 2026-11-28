"""Translate owner settings to C3 profiles without reading ambient provider secrets."""

from glassflow.modules.intelligence.assistant.prompts import PROMPT_VERSION
from glassflow.modules.intelligence.providers.policy import AIProfile, ModelRef
from glassflow.modules.intelligence.providers.settings import SECRET_NAMES, EnvSecrets, build_runtime


def runtime_for(settings, secret=None, ledger=None):
    safe = settings.model_dump() if hasattr(settings, "model_dump") else settings
    enabled = safe.get("profile", "local_limited") != "local_limited"
    provider = "judge_gateway" if safe.get("profile") == "judge_gateway" else safe.get("provider", "gemini")
    model = "gateway-pinned" if provider == "judge_gateway" else safe.get("model_id", "")
    # A KZT budget is never silently treated as dollars. Paid tariff/currency setup
    # requires an explicit supported C3 price profile; fail closed until supplied.
    paid = safe.get("mode") == "paid_enabled"
    profile = AIProfile(name=safe.get("profile", "local_limited"),
        primary=ModelRef(provider=provider, model_id=model) if enabled and model and not paid else None,
        mode="free_only", rpm=safe.get("rpm", 1), tpm=safe.get("tpm", 1000), rpd=safe.get("rpd", 100),
        max_concurrency=safe.get("max_parallel", 1), request_timeout_s=safe.get("timeout_seconds", 30),
        turn_deadline_s=safe.get("timeout_seconds", 30), max_retries=safe.get("max_retries", 2),
        max_output_tokens=min(8192, max(64, safe.get("max_output_tokens", 2048))),
        max_tool_iterations=safe.get("max_tool_iterations", 6),
        fallbacks=[ModelRef(provider=x.split(":", 1)[0], model_id=x.split(":", 1)[1])
                   for x in safe.get("fallback_models", []) if ":" in x] if enabled else [])
    return build_runtime(profile, EnvSecrets({SECRET_NAMES[provider]: secret or ""}),
        prompt_version=PROMPT_VERSION, ledger=ledger, env={"GLASSFLOW_GATEWAY_URL": safe.get("gateway_url") or ""})

from glassflow.contracts.platform import AISettings
from glassflow.core.domain_runtime import runtime_for


def test_included_quota_is_explicit_and_reaches_actual_runtime_without_network():
    settings = AISettings(
        profile="direct", provider="basisweb", model_id="gpt-6-luna", quota_token_budget=12345
    )
    assert runtime_for(settings, "test-only-secret").status == "invalid_profile"
    settings.included_quota_enabled = True
    runtime = runtime_for(settings, "test-only-secret")
    assert runtime.status == "available"
    assert runtime.profile.quota_token_budget == 12345
    assert runtime.profile.mode == "free_only" and runtime.client.quota_tokens_spent == 0

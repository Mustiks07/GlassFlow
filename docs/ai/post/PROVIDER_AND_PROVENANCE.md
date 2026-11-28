# Explicit model execution and included quota

Candidate supports `AssistantTurn.execution_mode=hybrid|model_first` (default hybrid).
`model_first` bypasses response cache and invokes the configured allowed profile even for
locally recognized text. `allow_ai=false` with model_first is rejected with HTTP 422.
Unavailable configuration returns `origin=fallback`, zero calls, local limited mode and a
reason. It is not a successful model answer or live acceptance.

`AssistantReply` adds execution_mode, origin (`model`, `deterministic`, `cache`, `fallback`,
`reuse`), cache_hit, model_call_count, model_attempts (`provider`, `model_id`, `status`,
`error_kind`), selected_provider, selected_model_id, verifier_reject_count. Every actual
provider attempt, including failures/retries, is counted in a task-local capture. Queue,
policy and budget rejections before sending do not count as HTTP attempts. Prompt cache
usage is separate from response cache. Quote origin links generated drafts to conversation
and turn. Mandatory product/processing ambiguity cannot be bypassed by a model tool.

BasisWeb is a separate provider, with fixed URL `https://api.basisweb.ru/v1/chat/completions`,
redirects disabled and the actual response model checked against the selected model.
No key, private capability URL or portal token belongs in this document or any artifact.
The key is fetched as `BASISWEB_API_KEY` through the server secret provider.

Opt-in requires `included_quota_enabled=true` in the server profile (environment:
`GLASSFLOW_AI_PROVIDER=basisweb`, `GLASSFLOW_AI_INCLUDED_QUOTA_ENABLED=true`). Presence of
a key alone does not enable this provider or change the default profile. The included
quota flag is independent from monetary paid mode. Default budget is 1,000,000 weighted
quota tokens, hard maximum 5,000,000. Explicit BasisWeb environment composition defaults
to concurrency 1 and output cap 512; the integrator can lower the cap to 256.

Quota weights pinned from the supplier catalog supplied by the integrator on 2026-11-28:

| Model | Multiplier | Input | Output | Cached input |
|---|---:|---:|---:|---:|
| gpt-6-luna | 1 | 1 | 5 | 0.1 |
| glm-5.3-flash | 2 | 1 | 1 | 1 |
| gpt-6.1-terra | 3 | 1 | 5 | 0.05 |

Before every network attempt the client reserves a conservative UTF-8 byte input estimate,
protocol allowance and the full output cap. Successful complete usage replaces that
reservation with a rounded-up weighted usage calculation. Reasoning tokens already included
in completion tokens are not counted twice. Missing usage, failures and cancellation retain
the reservation; retries reserve again. A delayed supplier meter displaying zero is not a
zero-cost claim. Remaining profile quota is checked atomically before I/O; exhaustion yields
fallback without another send. Session/process restart resets the in-memory profile counter;
the integrator must retain cumulative exam debit across runtime recreation and budget cycles.

Verification here uses `httpx.MockTransport` and scripted providers only. No live network
requests, quota consumption or product acceptance are claimed by this branch.

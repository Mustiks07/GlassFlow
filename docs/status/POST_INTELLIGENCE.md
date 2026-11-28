# Post-integration intelligence

Worktree: `GlassFlow-post-intelligence`, branch `codex/post-intelligence`, base `5648852d64189ffd7269c277002f6fbc40c8039a`.

## 2026-11-28 — P0 regression checkpoint

- Only the two explicitly disclosed minimal P0 reproductions were read. The independent examiner oracle, tests and evidence remain unread.
- Unspecified selected edge sides no longer produce a persisted, confirmable glass-only quote. A follow-up with unresolved required parameters supersedes the earlier active draft without rewriting its historical amounts. Confirmation also checks linked persisted assistant turns, protecting pre-upgrade incomplete drafts.
- Generic sensor requests no longer choose a SKU because a shorter catalogue name scored higher. Candidates with identical mentioned discriminators require one clarification; explicit model codes still resolve.
- Quote origin is persisted: explicit request / deterministic assistant / model assistant, linked conversation and turn.
- `uv sync --locked --all-groups`: passed.
- `uv run pytest tests/intelligence/test_post_p0.py tests/intelligence/test_api.py tests/intelligence/test_local_engine.py -q`: 42 passed. Real in-process FastAPI/SQLite regression tests, not live model acceptance or browser E2E.
- Next: explicit model-first/provenance API; separate opt-in BasisWeb adapter with conservative included-quota accounting and mock transport verification. No external AI calls or secrets accessed in this worktree.

## 2026-11-28 — provider/API early freeze

- P0 commit: `5b38b5f`.
- Added agreed execution_mode, honest model/cache/fallback provenance, selected-model metadata, real attempt counts including failed calls/retries, verifier rejection count. Contradictory model_first/allow_ai=false gives 422. Configured model-first bypasses response cache; unconfigured mode reports fallback/0 calls.
- Added separate BasisWeb adapter and explicit included-quota opt-in, exact HTTPS host/path, no redirects, model identity check, conservative usage/reservation limiter. Default provider/paid behavior unchanged. BasisWeb is not falsely marked free pricing or OpenRouter.
- `uv run pytest tests/intelligence/test_post_provenance.py tests/intelligence/test_basisweb.py -q`: 11 passed.
- Earlier P0/resilience/provider adapter subset: 45 passed. Full intelligence suite started; result will be recorded after completion.
- No external calls or keys used. First real candidate exam belongs to the independent integrator. In-memory quota cap is per runtime lifetime; cumulative run/restart debit remains integrator responsibility and is documented explicitly.
- Next: N04 refinement, persistent N07 review queue + read-only KB impact preview, N19 correction drafts and N17 measured extraction decision.

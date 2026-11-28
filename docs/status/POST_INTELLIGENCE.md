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

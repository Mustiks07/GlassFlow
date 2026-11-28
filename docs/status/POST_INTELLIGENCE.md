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

## 2026-11-28 — N04 / N07 / N19 implementation

- Full early-freeze suite at `2f3a7ee`: 316 passed, 3 skipped, 319 total. No live acceptance claim.
- Domain migrations/DTO commit `f7aa94d`; implementation `c5fc208`.
- Authorized dependencies: root central migration `8cabfaa` cherry-picked as `87d0bad`; platform `b3de4cd` merged to supply the matching Coordinator/export_context API. Initial tests before the platform merge correctly failed on the missing Coordinator argument; no check was disabled. The integrated startup and eight P0/provenance tests passed afterward.
- N07/N19: 10 API/shared-DB regressions passed (classified causes, persistence, isolation, version conflicts, read-only preview, real existing KB apply API, contest immutability, verified correction, unknown/ambiguous review, unchanged history, migration up/down).
- N04: 7 targeted regressions passed; baseline/candidate comparison has 9 controlled author cases, correct statuses 7→9, full totals retained 4/4, unnecessary manager parameter requests 2→0, no provider calls. Raw comparison JSON under `docs/ai/post/`.
- N17: no additional extractor promoted; no measured independent benefit. Existing deterministic dispatch defect was fixed without adding a model.
- Parent batch adapter was given `outcome_reasons` and `record_accepted_batch_reviews` contract. Root/platform owns coordinator registration and accepted-row callback wiring.
- Full final suite with JUnit evidence is running; results to follow. Root owns generated contracts, functional UI, real browser/live/provider exam and release artifacts.

## Final source freeze (before independent live exam)

- All independent assigned implementation is complete. N07/N19 API regressions: 11 passed, including closed batch preserving clarification without synthetic customer replies. `AnswerRow.clarification` is an additive nullable field.
- Canonical preview additionally calls the exact platform import validator before displaying impact. Confirmation checks only matching linked historical turns rather than materializing all dataset turns. Legacy pre-origin drafts have a dedicated confirmation regression.
- BasisWeb hardening: malformed text payloads fail closed, malformed/missing usage retains quota reservation, cancellation retains reservation and records the actual attempted call, error credential redaction occurs before truncation. Budget rejection before sending does not count as a model call.
- Affected provider/resilience/provenance subset after hardening: 32 passed. Ruff: all intelligence source/contracts/tests passed.
- Final full suite is still running; no source changes are planned after this freeze. Only verification/status evidence may follow.
- No actual provider requests, key access, paid mode enablement, buyer messages, oracle reads or final-material replacement occurred in this worktree.

## N19 final applicability guard

- A self-review reproduction found that legacy dialog quality can return a canonical bulk rate when the manager labels a 3-unit order as wholesale. N19 now checks the source quantity threshold independently: an unconfirmed/ineligible bulk threshold yields NEEDS_REVIEW without applicable price/text. An eligible threshold is rendered explicitly from KB. This isolated draft guard does not change the assistant engine, prompt, provider or independent model exam inputs.

## Shared QA applicability correction (root requested)

- Root requested repairing the underlying dialog QA defect, not merely leaving a draft guard. Shared `bulk_price_scope` now checks canonical per-product quantity thresholds and claim-local conditions. Known 3/99-unit orders receive ERROR with retail-unit correction 150; known 100+ orders use bulk 100; unknown quantity with an unqualified bulk claim is NEEDS_REVIEW. Same-clause conditional «от 100 шт» remains a valid rate fact for a smaller order, but cannot make its wrong total valid. An unsupported stated threshold below the catalogue minimum remains NEEDS_REVIEW.
- N19 reuses that shared applicability rule: known eligible retail correction can now produce a verified draft; unknown applicability stays review-only; explicit conditional bulk correction preserves its canonical threshold in the text.
- `uv run pytest tests/intelligence/test_post_bulk_applicability.py tests/intelligence/test_post_reviews.py tests/intelligence/test_dialog_quality.py tests/intelligence/test_review_regressions.py tests/intelligence/test_commercial_binding.py tests/intelligence/test_verifier_completeness.py -q --junitxml=docs/ai/post/bulk-qa-regressions.xml`: 77 passed. Existing verifier/commercial completeness rules unchanged and passed. Ruff passed.
- Full suite on the source freeze before this isolated shared QA change: 340 tests, 337 passed, 3 skipped. Full final suite will follow; the independent live assistant exam uses unchanged assistant/prompt/provider code.

## Final verification checkpoint

- Final source SHA: `8d48d15` (assistant/prompt/provider source freeze `12f4b6d`; shared QA applicability added afterward, unchanged assistant execution path).
- `uv run pytest tests/intelligence -q --junitxml=docs/ai/post/intelligence-tests.xml --tb=short`: exit 0, **354 tests: 351 passed, 3 skipped**, no failures/errors. The three skips are the parametrized generic unit-price sweep for patterned clear/bronze/grey 8 mm whose KB has no unit rate (`no unit price in KB`); separate unknown-price/handoff/NEEDS_REVIEW regressions pass. They are not live/key skips.
- `uv run ruff check backend tests scripts`: passed.
- `uv run python scripts/check_foundation.py`: passed; 14 immutable inputs, 66 requirements, 67 assigned acceptance scenarios, exact specification PDF preserved.
- Raw JUnit: `docs/ai/post/intelligence-tests.xml`; targeted commercial/QA JUnit: `docs/ai/post/bulk-qa-regressions.xml` (77 passed). Raw author N04 before/after and interpretation are in `docs/ai/post/`.
- Completed assigned independent scope: P0, provenance/model-first/BasisWeb adapter, N04, N07, N19, N17 no-promotion decision. Parent owns live independent exam, merged contracts/UI/coordinator hook, actual browser E2E, EXE and release. No live AI acceptance claim is made here.
- Next exact step for root: merge `8d48d15` plus this evidence-only checkpoint, regenerate shared OpenAPI/TypeScript, verify coordinator accepted-batch review hook/UI, run the sealed live assistant/QA exam and all release checks on the integrated SHA. No further child source changes pending.

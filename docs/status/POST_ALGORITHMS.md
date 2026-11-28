# Post-integration algorithms

Base5648852, branch codex/post-algorithms, worktree GlassFlow-post-algorithms. Owner Mustiks07.
Original case/spec/validators/evidence are unchanged. Runtime solver received the priority0 correctness fix described below; research candidates remain disabled.

## Implemented checkpoint

- N01 pure `modules/cutting/sale_readiness.ensure_sale_readiness`: trusted eligible originals from root;
  no search for already-ready baseline, evidence shortage before search, complete-group bounded relocation,
  area-floor + eligible-use master, separately labelled tradeoff, preserved baseline, full input/inventory/registry hashes.
  Alternative is an unsaved validated proposal, never auto-committed. Root supplies canonical sales evidence,
  queue integration and final recheck. A timeout is not proof of impossibility. Cold native startup can consume budget.
- N03 POST `/cutting/scarcity`: original Candidates preserved; optional exact CP-SAT joint proof for a known
  uncovered order and requested quantity. Baseline INFEASIBLE plus alternative FEASIBLE + independent C2 validator
  required. UNKNOWN/time budget -> no invented explanation. Current candidate order is not changed.
- N10 GET `/plans/{id}/new-requirements`: grouped dimensions/material/quantity/area/actual reason,
  is_active + scope(proposal/active/historical), current inventory token. Invalid/superseded strict export rejects.
  No procurement sheets/prices invented. Missing reason remains UNKNOWN_REASON; recorded edit reason preserved.
- N13 GET `/plans/{id}/geometry-margins`: exact edge/gap excess. Tempered uses only whole-piece±2 deviation;
  edge/gap fields null, no cut or failure probability implied. Read-only pilot enabled.

`uv sync --locked --all-groups` PASS. `ruff` scoped PASS.
`uv run pytest tests/cutting/test_post_insights.py tests/cutting/test_post_sale_readiness.py -q -o addopts=''`:
12 PASS in3.25s. Synthetic data is explicitly test data, not real demand/closed score.
Contracts sent to root before dependent UI; root approved plan scope and tempered semantics.

## Next

Complete further stale/ID/lock/invalid/persistence boundaries and full C2 suite; preregistered N11/N12/N14
comparison in docs/experiments/post_cutting/PROTOCOL.md, then run all trials and decide promotion. Baseline remains
production until criteria pass. Root independently integrates functional UI/actual E2E/packaging.
Explicit BEGIN architecture approved and implemented as described below.

## Snapshot and boundaries checkpoint

Root approved explicit SQLite BEGIN only when driver transaction is absent. C2 read_session now uses one WAL read snapshot; borrowed Session read_session(existing_session) retains caller commit/rollback/close ownership. Interleaved-writer and borrowed BEGIN IMMEDIATE rollback regressions PASS.
Added boundaries for nonoriginal/unknown eligibility, preserved requested locks, changed IDs/order, invalid budgets, invalid NEW projection and reserved scarcity alternatives. Full `uv run pytest tests/cutting -q -o addopts=''`:89 PASS/1 SKIP in114.24s; skipped600s profile not claimed run. Scope Ruff PASS. Timing copied separately; original C2 evidence restored.

## Priority0 first-complete correction

9s pilot found a valid-geometry incumbent with fewer than requested5 free originals. Preserved all observed rows in pilot-9s-partial.json, interrupted comparison, no promotion conclusions. Root approved fix: checked all-NEW seed before native/greedy, immediate deadline/cancel handling; strict requested minimum (no min(requested,available) relaxation), no published incumbent below requested free constraint, limited status if impossible. Engine version cutting-engine/1.1-min-free-incumbent. Requested locks remain independently checked before publication.
Target first-complete+N01:16 PASS; existing solver targets17 PASS; whole C2 after main seed fix94 PASS/1 SKIP92.63s (then one extra excluded-stock boundary separately PASS). Original quick coverage>=55.8080067%, geometry valid and five free retained. New20s paired study will freeze before running any new candidate; old9s history remains available.

## Additional bounded evidence

V2 protocol frozen at bb7f480, before running candidates: same six mathematical input hashes, declared reuse
after baseline correctness fix, all24 trials20s/1GiB/one OS CPU(11 on this Windows10 host), workers1 and native
threads1. PeakWorkingSet includes native allocations; parent samples limit every20ms, final high-water is
also recorded. Late incumbents ignored. No heavy600 profile, no hidden review exam read.

N03 HTTP/service experiment (`uv run python docs/experiments/post_cutting/scarcity_comparison.py`) runs real
FastAPI routes + SQLite on36 explicitly synthetic cases with changed IDs: quantity1/2, impossible joint order,
reserved alternative, nonscarce geometry,1ms fallback. All baseline payloads/order unchanged;11 warm proof
witnesses independently validated;18 negative cases no_proof;6 tiny budgets limited. Cold native import
consumed1044.15ms and returned limited without invented advice; remaining35 HTTP requests p95=28.26ms.
Developer-host performance is not a clean-machine acceptance result. Reproduction script and every response
saved in scarcity-comparison.json. Global candidate order is intentionally not promoted; optional proof is
separate. Root owns live dataset/E2E acceptance and the visible frontend state.

N13 read-only geometric margin pilot enabled: uses actual validated placements, edge5/gap3 or tempered
whole-piece deviation±2, never changes placement/tolerances/reserve and makes no defect probability claim.
No promotion of manufacturing-risk recommendations. Exact bounds regression is in test_post_insights.py.

Final whole C2 suite after every runtime change:95 PASS/1 SKIP/1 dependency deprecation warning in103.43s;
command `uv run python -` with `pytest.main(['tests/cutting','-q','-o','addopts=','--junitxml=.qa/post-cutting-final.xml'])`,
test process constrained to CPU0 to leave comparison CPU11 available. No test checks disabled; optional600s
profile remains skipped by its existing explicit flag. Scope Ruff PASS. Actual candidate timing saved separately;
tracked original evidence restored byte-for-byte. Logs/JUnit are in ignored .qa for root audit.

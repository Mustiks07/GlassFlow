# Post-integration algorithms

Base5648852, branch codex/post-algorithms, worktree GlassFlow-post-algorithms. Owner Mustiks07.
Original case/spec/validators/evidence and runtime baseline solver are unchanged.

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
Pending architecture approval: explicit BEGIN for C2 read_session to guarantee multi-query read snapshot.

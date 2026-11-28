# Actual HTTP changed-input acceptance — blocked on P1

Runtime source: `554adc1282c697846fece08c06d6d5ed0f2a98e7`. Transport: fresh local uvicorn/TCP port18484,
fresh shared SQLite under `.qa/new-inputs`. No API key, paid mode, evaluation KEY, mock port or direct DB mutation.
`report.json` is the evidence record. Overall status is **blocked_product_issue**, not an accepted release.

Observed:

- First full automatically accepted bundle:8.235s within120s total/30s export reserve. Baseline solver5s,
  bounded improvement requested6s. New source IDs everywhere; stock/order geometry, questions, CRM fields and
  dialog text changed. Original materials/KB bytes preserved. Future CRM labels removed before import.
- Six downloaded CSVs: five result files plus50-organization independent-v2 registry. Exact headers/UTF-8,
  changed ID sets/counts, unique25 picks, five original-piece cards and manifest hashes checked on disk.
  Five cards have at least three distinct current structured matches each. Applications remain proposals,
  with source evidence and assumptions; this is not proof of buyer interest.
- Unmodified organizer `validate.py`, SHA256 `0d2760772d128ce0724f0a7090eff474667fc5e376a1fc753f03ddb8b73dac4a`,
  ran against downloaded solution and the changed stock/orders: coverage0.558090, invalid0, missing0,
  165/298 parts, material replacement value960705₸. This is a changed-input result, not a hidden/open original score.
- Actual12s/4s-reserve run on1000 new unknown requests reached `RUN_WORK_BUDGET_EXCEEDED`, with100 durable
  parent-accepted rows. Its incomplete answers were not exported ready.
- An additional real API cancellation run completed the other four modules and cancelled the long assistant
  after256 accepted rows. Export is partial: solution/picks/verdicts/sale_cards/buyers, with no answers.csv.
  Duration of this additional phase was not recorded; top-level25.266s describes only the initial phase.
- Service/coordinator stopped and uvicorn restarted on the same SQLite. The accepted passport stayed identical;
  old downloaded artifact URLs still returned identical hashes; existing failed-row counts remained durable.

Blocking P1: explicit unknown SKU query «Сколько стоит неизвестное крепление ZETA-POST-18484, модель и параметры
неизвестны?» returned `answered/supported`, selecting the generic hidden mirror mounting hanger and its400/200₸
prices. No LLM call was made. This is a deterministic semantic defect, not a quota or hosting issue. It was sent
to the Intelligence owner. The probe criterion remains clarification/manager handoff, with no fabricated ready quote.

Reproduction after the fix: `uv run python scripts/post_acceptance.py --data .qa/new-inputs-final
--output docs/release/post/http-new-inputs-final`. Data directory must be fresh; the script refuses existing DBs
and occupied ports. It exits2 when product issues remain, even if independent filesystem/restart checks pass.
Wait for a frozen backend source tree before spawning; accepted-row source fingerprints intentionally reject mixed builds.

The retained files are actual imported/downloaded bytes. Historical failed harness URL/observer assertions were
fixed separately; no product rule was changed. Actual browser/EXE/clean Windows, online AI and human labor acceptance
are separate and not claimed by this report. No supplied final PDF/presentation/source input was replaced.

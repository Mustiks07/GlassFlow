# Independent HTTP model-first runner

Frozen semantic rubric remains d8a628c; oracle questions remain c6a7888 byte-for-byte. This adapter changes transport/provenance handling, not expected commercial facts or scoring. No external model calls were made by the reviewer while preparing it.

Run the real candidate app with the root runtime-settings bridge correction. Use a separate fresh app data directory. The owner/root retains the secret in RAM; never write its payload, command expansion, provider response headers, or portal capability to an artifact. Both commands use the reviewer worktree's Python environment and script. Replace PORT and SHA with the actual running application and product commit.

```powershell
# $settingsJson is supplied by the root's RAM-only secret retrieval, not a literal here.
$settingsJson | uv run python scripts/post_review_exam.py --base http://127.0.0.1:PORT --mode live --configure-stdin --preflight --candidate-code-commit SHA --out .qa/live-preflight
# Keep the SAME application process/profile; do not configure again.
uv run python scripts/post_review_exam.py --base http://127.0.0.1:PORT --mode live --candidate-code-commit SHA --out .qa/live-exam
```

stdin JSON is a settings object with `api_key`. Defaults are direct/BasisWeb/gpt-6-luna, included-quota opt-in, monetary free_only, paid disabled, budget 1,000,000 weighted tokens, output cap 256, concurrency 1, retries 0, no fallback models. Root may reduce the quota/output caps; cap >1m, output >512, paid mode and fallback models are rejected. No model credentials in arguments or environment are required by this runner. Secret settings are accepted only for a loopback app endpoint and only in explicit live mode. Configuration errors suppress the response body.

The first command contains five separate warmups, not any held-out exam question. Exit 0 with `TRANSPORT_OK_NOT_EXAM_ACCEPTANCE` means five selected-model replies with consistent per-request model-attempt provenance, not product acceptance. Review preflight details before continuing; stop on quota/auth/model errors. Full exam is 149 turns (79 questions, 35 critical questions three times), plus ten deterministic quality checks. Full result always requires independent semantic adjudication: `MANUAL_REVIEW_REQUIRED` exits 1, `BLOCKED` exits 2. Failure/partial result also exits 1. Local fallback/client correctness is reported separately and cannot raise selected-model accuracy; a selected-model transport/error/rejection attempt remains in its denominator.

The harness records profile, selected-model attempt metadata, initial/final weighted quota counters, per-turn HTTP latency and partial results. It stops when budget is exhausted or a profile/quota-counter reset is observed. Root must enforce the user's cumulative <=1m weighted-token cap across preflight, full exam, provider retries, process restarts and profile recreation. A restarted process's counter is not the account ledger: subtract all earlier debit from any replacement profile budget before sending further requests. Do not run two exam processes concurrently. A quota stop leaves remaining turns not_run, never PASS. Runtime/provider prompt or configuration changes after an exam start require a new named candidate/result; preserve previous evidence.

All live questions and results remain in the independent reviewer worktree until the candidate freezes. The two previously disclosed P0 cases are regression evidence; the remaining 77 questions are independent. No evaluation key, oracle, expected facts or scores are injected into production.

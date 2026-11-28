# POST_REVIEW — независимый экзамен и baseline

База5648852d64189ffd7269c277002f6fbc40c8039a. Worktree `C:/Users/User/Documents/ChatGPT/GlassFlow-post-review`, ветка `codex/post-review`. Product code/DTO/UI/миграции/original case/spec/official validators не изменялись. Исходный tested EXE3f83310 не тронут.

## Phase1

- Oracle freeze c6a788809e27648bcd24f3dcdcc779afba0cd6a5:79 assistant вопросов,10 QA,35 критическихx3,149 turns. Аргументированные ожидаемые действия/суммы — независимые Decimal source-KB formulas. Numeric Oracle неизменен после baseline.
- Algorithm corpus dd5fe2330eebb19ead8365adaa7c59908b08d334:12 входов/4 семейства/3 seeds, одинаковый10с/1worker/2GiB; не прогноз скрытого результата.
- System boundaries2710025/format01bcdc1: критерии N01–N19, controlled scarce/joint/eligibility datasets, deadline/restart/fencing/checkpoint/human/QR/NEW/passport и promotion gates условных экспериментов.
- Rubric1.1 semantics334c0c70023872a885c2582eb848d6067e68e8c2; final provenance/adapter freeze d8a628c1a3abf7a12ddfe316b38ebaece86c9611: исправлены ложные reviewer штрафы optional Quote и правильно квалифицированных дополнительных ставок; старый mechanical report/per-row grades сохранены. Ни production verifier, ни вопросы/ожидаемые суммы не ослаблены.
- Actual local HTTP baseline:149 turns,135 correct90,60%; разные69/79=87,34%; QA10/10; canonical quote controls55/55; provider calls0; p50/p95=33,77/56,75мс. Все149 deterministic, не live AI.
- P0-01: unknown selected-side edge → clarification, но typed quote loses processing/known glass-only total и confirm200. P0-02: общий sensor запрос → произвольно выбранная конкретная двойная модель/цена. Redacted repro раскрыт root; IR057/IR059 после раскрытия regression, оставшиеся77 independent. Не раскрывать полный oracle кандидату до его freeze.
- Live API capability probe BLOCKED/exit2: current main не умеет model_first/exact cache provenance; никаких provider calls. Root добавляет additive контракт отдельно. Старые C3 live75%/25из36 относятся к другим prompt/provider snapshots, не к этому v4 baseline.
- uv sync --locked --all-groups PASS; Ruff own files PASS; examiner unit12 PASS; foundation14+exact spec PASS. Это не прохождение всех новых функций или внешней приёмки.

Evidence: `tests/post_review/ai_exam_v1.json`, `system_scenarios_v1.json`, `human_tasks_v1.json`; `tests/post_review/evidence/baseline_5648852/{initial_report,adjudicated_report,adjudication_log,live_capability}.json`; `docs/reviews/POST_INTEGRATION_*`.

Скрипт `scripts/post_review_exam.py` обращается к настоящему HTTP приложению. Local exit0 означает завершённое измерение, не live PASS. Live без model_first/key блокируется exit2; model/cache/fallback/deterministic/reuse считаются раздельно. Любой будущий live PASS требует manual semantic review,>=95% и критическихx3; evaluator не меняет бюджет/профиль и не включает paid.

Внешние протоколы clean Windows11, real HTTPS gateway/new client/token revoke, минимум10 actual human pairs/U07 готовы. Людей/чистую Windows/hosting этот агент не заменял синтетическими тестами. Пустой measurement template содержит0 измерений. Buyer relevance/public activity/TLS и финальные материалы проверяются отдельно; исследовательская пригодность не спрос.

## Следующий шаг

Phase1 завершена; текущий tip этой ветки фиксирует evidence/status и освобождает слот Intelligence. Root использует redacted P0 до N04; после первого candidate freeze разрешает раскрытие остальных независимых случаев. Позже — phase2 на общей ветке: исполнимые fault tests новых API, local/допущенный capped live exam, browser/native/material evidence и замечания без само-приёмки собственного продукта.
# Second wave: BasisWeb transport adapter (2026-11-28)

Prepared strict top-level per-request provenance adapter and loopback-only stdin settings injection for EARLYFREEZE f7aa94d plus root runtime bridge correction. Five distinct transport warmups precede the frozen 149-turn exam. Configuration never automatically enables paid mode or fallback models; output cap <=512, included weighted budget <=1m, serial execution. Counter rollback/profile changes/quota exhaustion stop remaining questions as not_run. Root enforces the cumulative account cap across processes/profile recreation. Reviewer made zero external model calls during preparation.

Validation: `uv run pytest tests/post_review/test_exam_contract.py -q` 15 PASS; scoped Ruff PASS. AST comparison of grade/qualified_catalog_price/money_values/near against d8a628c unchanged; `git diff --quiet c6a7888 -- tests/post_review/ai_exam_v1.json` PASS. Command/protocol: docs/reviews/POST_INTEGRATION_LIVE_RUNNER_2026-11-28.md. Next: root runs five preflight requests with RAM-only secret stdin; reviewer independently audits results and all 50 buyer records, then N01–N19 on integrated candidate.


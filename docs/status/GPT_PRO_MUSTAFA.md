# Статус GPT_PRO_MUSTAFA

- Ветка: `codex/gpt-pro-mustafa-platform`; отдельный worktree `GlassFlow-platform`.
- Foundation: `16d63c6`.
- Обновление: 27 ноября 2026, Asia/Qyzylorda.
- Общий статус: IN PROGRESS. Это не COMPLETE VERIFIED PRODUCT.

## Проверенный этап P-01/P-02/P-04/P-05/P-06

Реализованы Alembic v1 с upgrade foundation и backup перед миграцией; SQLite WAL/FK/busy_timeout; короткий BEGIN IMMEDIATE UoW; atomic idempotency/body hash/replay и audit. Единый error envelope, локальные Host/Origin/session-token проверки.

Импорт: семь типов, CSV UTF-8/BOM, bounded ZIP, traversal/symlink/KEY исключение, построчные ошибки, immutable bytes/SHA/source rows, snapshot dedupe и явная рабочая копия. Import hooks выполняются внутри той же transaction; собственная mutable inventory/catalog не создаются.

CRM: reference-v1 stable baseline, ровно 25 заявок, сгруппированная клиентская очередь, observed precision только при наличии всех меток. Исторические M1-M5/unknown, фильтры, восемь представлений семи метрик с отдельной средней суммой всех заявок, Decimal, знаменатели, полнота и drill-down IDs. Напоминания: recipient отдельно, UTC, uniqueness, optimistic/idempotent transitions, stale recheck через dependency port.

## Проверки

- Foundation до изменений: `uv sync --locked --all-groups`, `pnpm install --frozen-lockfile`, pytest (7), ruff, check_foundation, pnpm typecheck/test/build: PASS.
- После этапа: `uv run pytest`: 17 PASS, включая реальные исходные counts 200/298/110/700/18/8 и baseline 20/25; synthetic rollback, isolation, конкурентный idempotency, без label, stale reminders.
- `uv run ruff check backend tests scripts`; `uv run python scripts/check_foundation.py`: PASS.
- OpenAPI и TS стандартно регенерированы, без ручных правок.

## Контрактные точки интеграции

`Services` в `core/registry.py`: import_hooks(session,dataset_id,parsed) должны только flush и не commit; subjects.check(session,dataset_id,type,ref,expected_version) возвращает valid/version/reason. Specific-remnant check обязан проверять совместимость и available через C2, quote_example - актуальную ревизию C3. При отсутствии зависимости 503; production fallback/fixtures отсутствуют.

Источник rows: `platform.imports.records(session,dataset_id,kind)`, неизменные исходные поля + source_row. Hooks должны принимать grouped rows public_id/source_row/data. C2/C3 migration snippets пока отсутствуют в этой ветке: регистрация и совместная DB остаются интеграционной проверкой.

HTTP: import commit/working-copy/reminder mutations требуют Idempotency-Key; GET health/session устанавливает local cookie. /session возвращает локальный токен для owner-only системных операций. Дополнительные поля DTO обратно совместимы.

## Остальной backlog

P-03 durable jobs/run coordinator; P-04 logistic evaluation/artifact; P-07 buyers/cards; P-08 strict exports; P-09 backup/restore/settings; P-10 launcher/frozen/CI/performance; P-11 gateway integration; P-12 economics/examples/release; P-13 общий handoff. Продолжать последовательно в этой сессии.

## Внешние условия и честные статусы

C2/C3 domain services и C1 verified buyer evidence не объединялись. Live provider/gateway, чистая Windows, ручные сравнения активного труда, team name, guest downloads и T63-T67: NOT RUN/BLOCKED до фактических входов/действий. Зеленые unit tests не закрывают эти сценарии.

## Следующий точный шаг

Реализовать durable process worker и run coordinator, затем обучить/оценить CRM candidate на одинаковых group/temporal/random splits без продвижения недоказанной модели.

## Checkpoint 2: durable pipeline, exports, safety (27 ноября)

- Предыдущий опубликованный commit: `9055924`.
- P-03: durable queued/running/completed/failed/cancelled/interrupted jobs; spawn CPU/network lanes; bounded cancellation, validated incumbent, restart interruption; coordinator-only result writer, optional atomic result_hooks. Прогон клонирует source в отдельный contest dataset. CRM работает; не зарегистрированные cutting/assistant/quality/cards получают SERVICE_NOT_REGISTERED; независимый CRM остается доступен.
- P-04: выполнены 13 outer splits и train-only inner GroupKFold tuning. `docs/release/crm/evaluation.json` и hash JSON candidate artifact. Temporal day90: baseline 0.76, model 0.32; reference-v1 сохранен, модель не promoted и не probability. Никакого пользовательского pickle/joblib loader.
- P-07: importer CSV+reviewer evidence, 50/30/5, allowed categories, score, names/entity dedupe, registry hashes; incomplete evidence -> needs_review. Cards используют injected C2 source/validator, original full piece, Decimal factor .30-.70, exact names/top3 IDs, versioned stale checks, factor/buyer edits. Реальный реестр C1 отсутствует; тесты явно synthetic.
- P-08: exact five CSV schemas + buyers separate, ID completeness/uniqueness, NEW empty fields, NEEDS_REVIEW blocked. UTF8 no BOM, temp/close/reread/fsync/atomic directory publication; immutable validate.py subprocess с UTF8 stdout/stderr/exit/hash. Partial CRM скачивается через API с manifest; export replay idempotent. Тест all-NEW является synthetic проверкой формата, не solver acceptance.
- P-09: server-side session-memory keys, free-only default, explicit paid budget; keys не сохраняются в DB. Backup SQLite API; исправлено реальное Windows file lock: sqlite connection context не закрывает handle, теперь используется contextlib.closing. Restore integrity/FK/schema, protected backups, explicit choice, maintenance и применение после restart.
- P-10: launcher bind socket before startup, free port, /ready wait, browser, instance locks, graceful shutdown; PyInstaller spec и build script. Native worker source smoke PASS (SciPy MILP x=2, OR-Tools x=2, spawn). Первая actual Windows frozen сборка выполняется; результат еще NOT RUN.
- Проверки: `uv run pytest` 33 PASS; ruff/check_foundation PASS; standard OpenAPI/TS regenerated. Foundation UI не менялся.
- Следующий шаг: actual frozen worker/backend/restart smoke, CI и performance; gated PDF/economics/examples/release tools и финальный handoff. Доменная интеграция/real AI/clean Windows/реальные buyers/manual labor measurements остаются отдельными блокерами.

## Checkpoint 3: Windows, release tooling и итоговая платформа

- Автор следующих commits: Mustiks07, GitHub noreply identity, worktree-only config. Старые опубликованные commits не переписывались.
- На фактической Windows build машине собран PyInstaller onedir. Первый native smoke выявил пропущенные OR-Tools DLL; исправлено collect_dynamic_libs. Повторный actual EXE smoke PASS: frozen child SciPy/OR-Tools x=2, HTTP import, CRM25, скачанный picks.csv, штатный shutdown, restart/persistence. Evidence `docs/release/frozen-smoke.json`; clean Windows/полный UI flow остаются NOT RUN.
- Новый Alembic head `0002_immutable_history`: SQL triggers запрещают изменение/удаление original bytes, source rows, audit, replay и dataset identity. Старый head не редактировался; upgrade делает online backup.
- Jobs: retry_of/new attempt/idempotency, latest attempt per module, bounded CPU/network processes, RSS guard, actual timestamps. Network secrets передаются только memory-only context.private_config, не snapshot/SQLite. AI jobs не получают CRM applications; модульные snapshots минимальны. Typed SolveInput mapping готов для C2.
- Specific-remnant reminder требует compatibility_ref/version (quote/part), resolver возвращает compatibility_valid/version. Проверяются и версия куска, и версия обоснования совместимости; тестируются stale по обоим источникам. SalesSourcePort добавлен обратно совместимо, детали в handoff.
- P-10: launcher/single instance/free port/static UI; frozen source digest/build stamp; Windows CI и native smoke artifact. Remote CI пока не объявлен PASS.
- Actual benchmark: import preview 20, median 65.37 ms / p95 105.19 ms; dashboard100 median 70.00 / p95 128.38 ms; CRM100 median 41.81 / p95 104.85 ms. CPU/RAM/OS/samples в `platform-benchmark.json`. Измерения выполнялись во время сборки, не на эталонной чистой машине.
- P-11: safe settings и HTTPS probe/integration guide готовы. C3 gateway engine/hosting/endpoint/token/quota отсутствуют: deployment и real full flow BLOCKED.
- P-12: evidence-gated one-page economics и шестистраничный examples renderer; formulas без double count/payback при net<=0; минимум10 real paired labor studies. Synthetic layout PDFs отрендерены Poppler и просмотрены, кириллица/таблицы/схемы без обрезания. Это НЕ final economics/examples для жюри. Без actual C2/C3/manual evidence final build отказывается.
- Release assembler требует ready same-run пяти CSV + buyers, hashed visually reviewed PDFs и team README; не перезаписывает существующий финал, исключает KEY/DB/secrets и synthetic provenance. Конкретный frozen bundle просканирован, source licenses metadata собрана без локальных machine paths. T67 legal acceptance NOT RUN.
- Полный контроль перед этим checkpoint: pytest42 PASS, ruff PASS, check_foundation14 immutable PASS, pnpm typecheck/test (2)/build PASS, generated contracts обновлены. Последние изменения privacy snapshots/release fixture guard дополнительно проверяются перед финальным push.
- Открыты и прочитаны README, actual downloaded CSV/manifest; synthetic PDF previews просмотрены все страницы. Final presentation/реальные buyers/final PDFs отсутствуют в этой ветке, не подменялись генерацией.

## Передача интегратору

Основной отчет: `docs/release/PLATFORM_HANDOFF.md`. Календарь T63-T67: `SUBMISSION_CHECKLIST.md`.
Оставшиеся внешние/совместные пункты: C1 UI и real buyer evidence; C2/C3 actual repositories/migration snippets/handlers/validators; live providers и HTTPS gateway; team name;10 real paired labor timings/cost assumptions; actual run economics/examples; clean Windows; guest downloads/submission/attendance/rights.
Ни один из этих пунктов не считается PASS по платформенным fixtures. Статус: PLATFORM IMPLEMENTED / INTEGRATION REQUIRED; полная конкурсная миссия еще не принята.

## Заключительное согласование интерфейсов соседей

После fetch прочитаны C2 `0e2abce` и C3 `e83c211`: их engine/migration snippets опубликованы, здесь не объединялись.
C1 `12c5a23`: buyer registry/evidence отсутствует, status начальный. Предыдущие записи об отсутствии относятся к foundation этой ветки.

По их конкретным запросам реализованы app.state.job_submitter (cutting.solve -> durable queue),
app.state.intelligence_sources (общие БД/исходные bytes/KB history), app.state.crm_port (тот же CRM HTTP service).
Добавлен versioned workspace KB upload/head/revert; original source и contest не меняются. Короткий WAL read snapshot
защищает согласованность KB history/head. C3 httpx dependency теперь явно в intelligence group/uv.lock.
C2/C3 migration directories автоматически включаются в PyInstaller, когда появятся после merge; общая ревизия их применения
намеренно не stamp-ится без самих доменов.

Compose target под реальный C3 Dockerfile/healthz/readyz/v1/turn подготовлен; `docker compose config --no-interpolate --quiet` PASS.
Docker CLI28.5.1 установлен, daemon pipe отсутствует; actual image build/deploy, TLS, ключ, квота BLOCKED.

Расширение frozen smoke нашло реальный Windows singleton дефект: чтение заблокированного byte lock до try.
Исправлено на stat размера без чтения locked byte. Новый smoke дополнительно проверяет second instance, защищенный
официальный validator CLI (synthetic all-NEW только формат), unchanged CRM selfcheck на реальном скачанном open picks,
normal restart и backup/restore через actual EXE. Ожидает заключительного прогона после этого commit, не считается PASS заранее.

Проверки новой сборки исходников: 47 pytest PASS, ruff PASS, check_foundation14 PASS, pnpm typecheck PASS;
до последних адаптеров также typecheck/test/build PASS. PDF builders теперь защищают существующие финальные файлы от перезаписи.

| Пункт | Фактическая граница |
|---|---|
| P-01 | platform DB/Alembic/UoW/errors/idempotency/audit/DI done; domain migrations применяет интегратор после merge |
| P-02 | importer/bytes/SHA/snapshot/working copies/KB history done; domain import hook activation требует объединенных моделей |
| P-03 | durable queue/process/cancel/retry/run/export coordinator done; actual C2/C3 handlers/result hooks — интеграция |
| P-04 | baseline + grouped queue + train-only logistic comparison/artifact done; baseline выбран, closed score unknown |
| P-05 | reminders/UTC/uniqueness/version/stale done; actual C2/C3 subject resolver — интеграция |
| P-06 | historical seven metrics + denominators/completeness/drilldown/filtering done; UI C1 приемка остается |
| P-07 | registry/cards/prices/source checks done; real C1 registry и actual selected C2 plan отсутствуют здесь |
| P-08 | strict same-run CSV/download/atomic validation done; whole real five-module run после merge |
| P-09 | local auth/secrets/session/backup/restore/immutable history done; совместные domain concurrency проверки после merge |
| P-10 | onedir/native worker/launcher/CI/benchmarks done; финальный smoke обновляется; clean PC и C2/C3 timing NOT RUN |
| P-11 | settings/actual C3 deploy contract/Compose/probe done; hosting/key/daemon/quota/full judge flow BLOCKED |
| P-12 | gated PDF/report/release builders, source licenses, README/calendar done; final PDFs требуют actual run, human timings, team/costs |
| P-13 | platform tests/evidence/handoff done; общая приемка и T63-T67 не выданы за PASS |

Точный следующий шаг: закончить actual frozen smoke с singleton/validator/backup restore, записать SHA и CI,
опубликовать evidence/status от Mustiks07. Runtime код готовится к интеграции; main не трогать.

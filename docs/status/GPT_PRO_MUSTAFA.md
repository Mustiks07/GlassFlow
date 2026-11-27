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

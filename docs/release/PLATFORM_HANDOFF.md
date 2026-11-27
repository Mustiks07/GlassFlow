# Платформа GlassFlow: handoff интегратору

Ветка `codex/gpt-pro-mustafa-platform`, foundation `16d63c6`.
Не объединялась с main или соседними агентскими ветками. Новые коммиты после настройки автора идут от Mustiks07.
Точные SHA/последние проверки — в `docs/status/GPT_PRO_MUSTAFA.md` и `git log`.

**Граница результата:** независимый платформенный объем реализован и проверяется на настоящей SQLite/HTTP/Windows EXE.
Это не COMPLETE VERIFIED PRODUCT. Реальные C2/C3 сервисы и C1 UI/buyer evidence не подключены;
полная приемка, закрытый run, live AI, final PDF, clean Windows и подача не объявляются выполненными.

## Подключение модулей

`create_app(data_dir=None, services=Services(...))`. Production lifecycle берет отдельный database.lock;
SQLite лежит в LOCALAPPDATA/GlassFlow. Сессия — `request.app.state.session_factory`;
explicit writer — `core.uow.write_transaction`. Вложенные доменные сервисы только flush, **не commit**.
Сетевые вызовы/solver не выполняются в writer transaction.

`Services`:

| Точка | Контракт | Владелец потребителя |
|---|---|---|
| import_hooks | `(session,dataset_id,grouped_rows)`; все kinds имеют `{public_id,source_row,data}` включая KB; одна transaction с source snapshot | C2/C3 |
| job_handlers | `{kind: Handler(importable_function,lane,validate,timeout_seconds,memory_limit_mb)}` | C2/C3 |
| result_hooks | `{kind: hook(session,dataset_id,result)}`; atomic savepoint + job publication; failure не останавливает независимые jobs | C2/C3 |
| subjects | `SubjectResolver.check(session,dataset_id,type,ref,expected_version,...)` | C2/C3 |
| sales_source | `SalesSourcePort` в ports.py: current selected get_plan, independent validate_plan, current get_remnant | C2 |
| ai_check | bounded sync/async `(settings,session_secret)` -> allowlisted connection fields | C3 |
| readiness | per-module actual local probes; наличие handler само по себе не дает ready | C2/C3 |

Subject resolver возвращает valid/version/reason. Для specific_remnant обязателен явный compatibility_ref/version
(например сохраненный quote/part), не придуманная связь адресата с заказом. Resolver проверяет совместимость,
возвращает compatibility_valid и compatibility_version. Создание, открытие и confirm перечитывают источники;
изменение quote или остатка делает задачу stale. Расчет остается за своим customer; recipient отдельно.

SalesSourcePort добавлен обратно совместимо как новая граница, существующие CuttingPort/IntelligencePort не менялись.
`get_plan` должен вернуть текущую выбранную ревизию именно запрошенного ID. C2 не должен выдавать произвольную
историческую validated ревизию как текущую. Free_original IDs перепроверяются по source records, placements и availability.

### Миграции

Единая Alembic цепочка: `0001_platform -> 0002_immutable_history`. До upgrade создается SQLite backup.
V2 делает source_files/source_records/audit/idempotency append-only и защищает identity/hashes/counts dataset.
Доменные migrations C2/C3 в этой ветке отсутствуют. Интегратор регистрирует их в **одной следующей ревизии**,
обновляет head/readiness/restore compatibility, проверяет fresh + upgrade + backup. Не создавать две головы и не
заменять миграции `create_all`. Не пытаться записывать mutable inventory в immutable source_records.

## Jobs и run

Один coordinator пишет worker messages в БД. CPU lane — один process; внутренние потоки C2 <= CPU-1.
Network lane — отдельный bounded пул двух processes. Spawn/freeze_support проверяются actual EXE.
Progress stage/counts без придуманного процента; incumbent только после независимого Handler.validate.
Cancel requested и stopped различаются; после grace process завершается, last_valid_result сохраняется.
Конечный deadline и RSS budget (default 2 GiB) ограничивают зависший worker. Windows/Linux RSS monitor;
на иной ОС monitor может вернуть unavailable, что требует отдельной приемки.

На restart queued/running получают interrupted, не completed. Retry создает новую job с retry_of, без
повтора подтвержденных предметных мутаций. Run/export выбирают последнюю попытку каждого module.

Handler — top-level importable function `(snapshot:dict, context:ProcessContext) -> dict`.
Не передавать session/engine/closures в spawned процесс. Snapshot сериализуем, keys не хранятся в JobRow.
Network worker получает provider secret только через `context.private_config` из памяти родителя;
safe ai_settings заморожены в snapshot. Нельзя выводить private_config в result/provenance/logs/prompts.
Lane=`network` обязателен для сетевых batch handlers. Сам C3 ограничивает RPM/TPM/RPD, retries, total deadline/tools,
запрещает paid fallback при free_only и возвращает фактическую provider/model/prompt/usage provenance.

Run принимает immutable source, проверяет оригинальные materials/KB, клонирует отдельный contest dataset;
source/workspace/reservations не смешиваются. Для C2 есть `snapshot['cutting_snapshot']` — сериализованный SolveInput
из `core/snapshots.py` (DTO mapping, без собственного solver). Для C3 есть original questions/dialogs/KB rows.
CRM handler использует тот же rank_rows, что HTTP. Cards запускаются только после cutting completion.

### Результаты handlers для экспортера

| kind | Envelope |
|---|---|
| cutting | rows exact solution schema; plan_id, plan_revision, validated=true; provenance с actual algorithm/config/validation |
| assistant | rows id/answer; needs_review; provenance actual provider/model/prompt/KB/tools/usage |
| crm | rows app_id; policy, observed_precision nullable; provenance reference-v1 |
| quality | rows id/verdict/correct; unresolved NEEDS_REVIEW блокирует export; actual provenance |
| cards | card_ids из сохраненного sales service, plan_id, plan_revision; не hand-made строки/цены |

Cards result_hook может вызвать `sales.service.generate_cards` на writer session и сохранить IDs; цена считается
этой общей функцией, не worker/LLM/exporter. Это короткая CPU операция после final C2 result; никакой сети внутри hook.
При недостатке 5 целых исходных кусков сервис дает RECOMPUTE_REQUIRED, не объявляет фиктивную coverage delta.
Фактическое сравнение делает C2; платформа не дублирует геометрию.

Экспортер: точные колонки; уникальность/полнота ID; 25 picks; 5 original free cards; exact buyer names по IDs;
NEW имеет пустые coordinates/rot; OK имеет пустой correct; только OK/ERROR. UTF-8 no BOM, comma/escaping,
temp -> close/fsync -> reread -> immutable official validator -> atomic publication. Validator идет вне DB lock.
При failure stdout/stderr/exit/hash сохраняются в manifest, не публикуется invalid solution/cards.
Готовые независимые части скачиваются с partial. Официальные закрытые AI/CRM/QA scores — null без KEY.

## Покупатели

`POST /buyers/import?dataset_id=...`, multipart file/evidence, Idempotency-Key.
CSV exact: name,city,category,url,why,source_url,score.
Evidence JSON: `{dedupe_policy,records:[{name,city,profile,source_url,checked_at,reviewer,confirmation,entity_id}]}`.
Нужны 50 unique, >=30 Astana, >=5 разрешенных categories; integer score 0–100; URLs и reviewer evidence.
Недостаток evidence -> needs_review, final registry/cards blocked. Verified означает проверенную согласованность
предоставленного reviewer evidence, не факт будущей покупки. C1 сохраняет actual online проверки и provenance;
если его формат другой, требуется явный adapter, не выдумывание недостающих полей.

Реальный buyers_candidate/evidence отсутствовал в доступной foundation ветке. Тестовые synthetic organizations
на example.test не поставляются пользователю и не являются итоговым buyers_top50.csv.

## Фактическая проверка

- Исходные реальные counts 8 materials, 200 stock, 298 parts, 110 orders, 700 applications, 18 questions, 8 dialogs.
- Runtime reference baseline 20/25 на open; без label ranking тот же, observed_precision=null и returns=N/A.
- Model evaluation: 13 outer splits, inner preprocessing/tuning только train. Temporal day90 model 0.32 vs baseline 0.76;
  frozen policy остается reference-v1. JSON artifact не исполняемый pickle, hash/version/features сохранены.
- SQLite crash rollback, concurrent idempotency и optimistic conflict; immutable SQL triggers; stale inventory/quote tasks;
  owner/session/Origin/Host, secret not in DB; online backup и protected restart restore.
- Все пять CSV на других ID проверены **с явными test-only C2/C3/buyer fixtures** и реальным validate.py. Это проверка
  платформенных стыков/форматов; T50 whole-product acceptance остается интеграционной.
- `docs/release/frozen-smoke.json`: actual native EXE + spawned SciPy/OR-Tools + HTTP import/CRM/export/restart.
  Это build-machine evidence, clean-Windows T54 и полноценный UI flow не выполнены.
- `platform-benchmark.json`: 20 import preview, 100 dashboard, 100 CRM; actual samples/median/p95/machine/RAM.
  Quote/search/solver/live-AI/full-run не измерялись: blocked C2/C3.
- PDF generator прошел text/page-count и визуальную проверку synthetic layout. Final economics/examples отсутствуют
  до actual results/manual labor evidence; preview не экспортируется под видом финального PDF.

## Команды интеграционной приемки

```powershell
uv sync --locked --all-groups
pnpm install --frozen-lockfile
uv run ruff check backend tests scripts
uv run pytest
uv run python scripts/check_foundation.py
uv run python scripts/export_openapi.py
pnpm contracts:generate
pnpm typecheck
pnpm test
pnpm build
./scripts/build_windows.ps1
uv run python scripts/smoke_frozen.py
uv run python scripts/scan_release.py dist/GlassFlow
```

После объединения DTO регенерировать OpenAPI/TS, не выбирать вручную сторону конфликта.
Frontend/lock этой веткой не редактировались. CI добавляет Windows build/native smoke/artifact, но remote CI
не объявляется PASS без фактического результата runner. Python/frontend licenses inventory — metadata, не T67 approval.

## Порядок оставшейся общей приемки

1. Зарегистрировать actual C2/C3 repositories/import hooks/migrations/handlers/source resolvers и probes.
2. Source import + workspace price/measurement/reserve/consume; конкурентный резерв, replay и crash atomicity
   именно в общей SQLite transaction, без nested commit.
3. Новый immutable run с реальными solver/assistant/QA/cards/buyer registry; ошибка одного модуля, cancel/retry/restart.
4. Подключить C1 UI к session header/idempotency/version/compatibility contracts. Весь новый пользовательский маршрут,
   1366×768/125%/keyboard, актуальные stale состояния. Readiness нельзя включить одним наличием router.
5. Actual C3 gateway deployment/TLS/expiry/quotas/paid refusal и новый компьютер <=5 min. Hosting/account/token отсутствуют.
6. Реальные 10 manual/app paired labor tasks, actual plans/baseline, AI usage/cost и team name. Выпустить PDF,
   отрендерить и открыть все страницы. Проверить CSV/PDF/README/UI/слайды по одному run.
7. `assemble_release.py` принимает только ready same-run export, реально просмотренные hashed PDF и final README с team.
   Создает новую папку, не перезаписывает чужой финал; KEY/secrets/runtime DB исключены. Публикация/Drive — отдельное действие.
8. Clean Windows, гостевое скачивание, фактическая подача/заморозка/явка и юридические условия: только actual evidence.

Статус: **PLATFORM IMPLEMENTED / INTEGRATION REQUIRED**. Полная миссия с внешними приемочными условиями
остается незавершенной до перечисленных фактов; это явный checkpoint, не заявление о готовой конкурсной версии.

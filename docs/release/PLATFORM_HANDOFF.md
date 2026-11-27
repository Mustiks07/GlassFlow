# Платформа GlassFlow: handoff интегратору

## PRO-U01-F1 после review main25e433f

На исходном `9c59c8a` дефект независимо воспроизведен с **настоящим DTO C3 6cc73b9**,
загруженным только в память отдельного процесса: заказ C-test принял Quote.customer_id=C-other,
bind/confirm/reserve200. Никакие C3 source файлы не изменялись. После fix тот же compatibility-прогон:
другой клиент409 QUOTE_CUSTOMER_MISMATCH; anonymous409 QUOTE_CUSTOMER_REQUIRED; matching client200/200/200.
Это проверка HTTP/SQLite+DTO с explicit test adapter, не end-to-end C3.

Новый платформенный `OrderFacts.quote_customer_ref` обязателен по смыслу для bind: он приходит из C3 stored owner,
не из order/customer request. Default null оставлен только для чтения старых snapshots. Если C3 DTO уже имеет
customer_id, противоречие с explicit owner блокируется409 QUOTE_CUSTOMER_INCONSISTENT. Подробности в общем контракте.
Anonymous нельзя автоматически сделать расчетом клиента заказа: сначала explicit assignment в C3 или новый quote.
Изменение owner между bind/confirm/reserve -> durable stale+stale_code, формы скрыты; старые snapshots сохранены.
Конфликт внутри reserve откатывает inventory mutation. Имеющийся чужой quote не переписывается платформой.

`tests/platform/test_orders.py`:18 PASS (прежние4 +14 F1 cases): matching/other/null/legacy owner,
изменение до confirm/reserve, durable stale/restart/history, extended C3 customer_id contradiction,
post-reserve owner mutation rollback. Две новые bind-регрессии до runtime fix были FAIL (200 вместо409).
Actual C2/C3 integration повторить после объединения; старый локальный EXE report относится к070d0c8,
а не автоматически к этому исправлению. Общая миссия остается INTEGRATION REQUIRED, U04/U06 — следующий уровень.
Полный source suite после F1:72 PASS; Ruff/foundation14/typecheck PASS, contracts стандартно регенерированы.
Fix `e247927bfb01b4e796786ac13048421ac085017a` отправлен от Mustiks07.
[CI46050467129](https://github.com/Mustiks07/GlassFlow/actions/runs/46050467129): SUCCESS Linux и Windows,
включая72 tests и новую EXE build/smoke/scanner/artifact. Последующие изменения — только документационная evidence.
Остаток собственной очереди Pro: U04/U06 еще не реализованы; «F1 исправлен» не означает полную миссию или общий product PASS.

## Дополнения v1.1 после checkpoint052255d

Из актуального main прочитаны review/upgrade plan на `eaf81d6`, без merge. Все изменения только в платформенном
владении, новые commits от Mustiks07. Главный контракт для C1/C2/C3:
[`UPGRADE_CONTRACTS_v1_1.md`](../architecture/UPGRADE_CONTRACTS_v1_1.md).

| Блок | Реализация / свидетельство | Граница приемки |
|---|---|---|
| PRO-R1/A04 | `cd832a3`: управляемый Event-test воспроизвел старые CSV+refs/новый provenance на052255d, после fix4 export tests PASS | bytes/refs/deep-copied provenance в одной transaction; validator без writer lock; следующий export выбирает новый job |
| A04 accepted bundle | `070d0c8`: accepted_export_id/accepted_files обновляются только full-ready | failed retry/partial не заменяет ссылку на прежний ready, старые файлы доступны |
| U01 | contract `c3a373e`, implementation `ea02dff`;4 transactional tests PASS | real C2/C3/UI acceptance NOT RUN, synthetic seam tests явно названы |
| U03 | contract `8e7a09f`, implementation `869686a`;12 sales tests PASS | реальные public activity evidence дает C1; новое evidence не придумано Pro |
| A02 | prereg `f083b8e`, experiment `9b326d2`;18 splits/4 candidates,2 leakage tests PASS | независимого контроля нет, baseline retained; closed score unknown |
| U07 | contract `bc4e3f3`, implementation `38c0705`;4 economics/report tests PASS | scenario API/PDF, не final economics; human timings и ready same-run еще нужны |

Полный source suite после U07:58 PASS; Ruff, immutable foundation14, frontend typecheck/test2/build PASS.
Последующий A04 проверен отдельно4 export tests. Новая Windows evidence/CI фиксируются в status, не переносятся
автоматически с прежнего runtime0457954. Старые разделы ниже — предыдущий checkpoint.

Итог: на `762094c` повторно58 pytest/Ruff/foundation PASS, [CI46048150892](https://github.com/Mustiks07/GlassFlow/actions/runs/46048150892)
**SUCCESS** оба Linux/Windows jobs, новый EXE smoke/scanner/artifact. Local build `070d0c8` (runtime не менялся):
expanded smoke с U01 draft+fail-closed503 и U07 synthetic native PDF/hash/restart PASS. Report `frozen-smoke.json`,
машиночитаемые границы `upgrade-validation.json`. Старый frozen report заменен actual новым, не перенесен как PASS.
Actual downloaded native scenario PDF также отрендерен/просмотрен. Human timings и финальные economics/examples
по-прежнему не созданы из synthetic evidence.

### Что подключить агентам

- C2/C3: `Services.order_source: OrderSourcePort`, typed OrderFacts/OrderReservation. capture читает CURRENT
  Quote/KB/mapping+Remnant/compatibility, reserve/release/check работают в переданном Session без commit/network.
  C2 гарантирует физическое уникальное владение и возвращает post-reservation version; C3 own reservation не должна
  сама по себе делать цену устаревшей. C2 conflict содержит актуальный источник и альтернативы.
- Pro не создает mutable inventory/quote. Лист заказа только workspace: create/bind/confirm/reserve/warehouse-check/
  handover/release/cancel/reminder; exact versions+Idempotency-Key. warehouse-check требует человеческой заметки,
  handover не является подтверждением расхода материала. Полные исторические sheets в immutable audit, новой
  migration/head не нужно. Update source -> durable stale; offer/task скрыты, исторический confirmed документ доступен.
- C1: обе формы брать из OrderSheet.offer/warehouse_task с единым facts_hash/revision. Не рисовать собственную цену,
  показывать unknown location, conflict alternatives и distinct states. Новые routes/DTO есть в regenerated contracts.
- C1 U03: дополнить evidence.records[].applications (schema BuyerApplicationEvidence). CSV остается прежним.
  Публичная деятельность и размерное допущение раздельны. Без трех подходящих организаций на пять кусков cards409,
  старый keyword fallback удален. GET buyers/matches читает current remnant; tempered+cutting исключается.
  SaleCard.buyer_matches имеет3 точных registry IDs/names+versions/URL/date/ограничения; C3 формулирует только из них.
  Legacy unexplained cards нужно regenerate. Reserved/deleted/changed source -> stale/export blocked.
- C1 U07: scenarios POST/PUT/GET/PDF с version, decimal-string result backend. JS формулу не дублировать.
  PDF получает ровно ту же historical version, input/result hash и economics-v2. Числоошибок/rework/active time
  хранятся с operator/timezone intervals/result refs, минимум10 пар. PDF один page; synthetic/supplied evidence
  явно подписано; negative net дает payback=null. Потенциальные продажи и actual revenue не превращаются в прибыль.

Actual U01 two-manager inventory/E2E, C1 source audit/U03, U07 real labor и final PDF пока NOT RUN.
U04/U06 из следующего уровня плана не объявлены реализованными этим расширением: нужны aggregate basket
quote/stock contracts C3/C2 и подтвержденное потребление с reason; повтор reserve/cancel не должен создавать usage.
До их интеграции handover листа — человеческая передача, а material_use_fraction — явное сценарное допущение.

Команды: `uv run pytest`, `uv run ruff check backend tests scripts`, `uv run python scripts/check_foundation.py`,
`uv run python scripts/compete_crm.py`, стандартные regeneration/typecheck/test/build, Windows build/smoke/scanner.
В A02 повторно использованы все open rows: новый partition не назван новым независимым контролем.

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

## Уточнение после заключительного fetch соседних веток

Просмотрены (без merge): C2 `0e2abce`, C3 `e83c211`, C1 `12c5a23`.
C2/C3 объявили module READY FOR INTEGRATION; real buyers/evidence в C1 branch по-прежнему нет,
его status остается начальным. Старые формулировки «отсутствуют в foundation» описывают эту платформенную ветку,
а не утверждение об отсутствии опубликованной работы соседей.

По конкретным запросам добавлены реальные точки:

- `app.state.job_submitter = DurableJobSubmitter`: C2 submit("cutting.solve",dataset_id,SolveInput-dict)
  -> durable platform Job. Нормализуется в handler kind cutting, одинаковый envelope cutting_snapshot/config для run и UI.
  Нет handler -> 503 до постановки; scope/CPU/time проверяются. Результат сохраняет result_hook C2 в parent transaction.
- `app.state.intelligence_sources = PlatformIntelligenceSources`: C3 knowledge_base/kb_history/materials из общих
  immutable SourceFile bytes, SHA и aliases kb-<sha16>. Короткий WAL read snapshot согласует history/head при concurrent edits.
- `GET/POST /datasets/{id}/kb`: текущая версия/ревизия и upload новой KB только workspace. POST multipart file,
  expected_version (версия KB head, не Dataset.version), Idempotency-Key. Original source не изменяется;
  документы новых версий append-only в source_files, head pointer версионируется. Revert старых bytes явен,
  история не теряется, immutable contest и материалы не меняются. Рабочая копия сохраняет историю/head.
- `app.state.crm_port`: rank/draft_reminder вызывает тот же CRM service, что HTTP; canonical uniqueness защищает
  повтор AI tool, recipient не становится quote customer. Для specific_remnant C3 tool/UI должны передать compatibility_ref/version.
- C3 app.state.intelligence_service должен быть собран интегратором с этими sources/ports и общей session factory;
  production не должен оставаться на PackDirectorySources/open-pack bootstrap.
- C2 migrations/0001_cutting.sql и C3 migrations/intelligence_0001.py известны; их применение остается новой общей
  Alembic ревизией после merge. Нельзя условно stamp отсутствующие домены как мигрированные. PyInstaller уже подхватывает
  domain migration directories, когда они появятся после интеграции.
- C3 requested httpx явно добавлен в intelligence group/lock. C3 gateway /healthz/readyz/v1/turn учтены в probe и Compose target.
  Compose config прошел; actual Docker daemon/HTTPS/key/quota отсутствуют. Подробности infra/judge-integration/README.md.

Не дублировать в runtime C3 valuation helper и Pro sale card price: финальная карточка/HTTP/export используют
`sales.service.card_price`. Общие domain DTO по-прежнему брать из объединенных feature files, не копировать их в Pro.

Для worker adapters: C3 check_dialogs/_check и effective_mappings используют persistence. Нельзя передавать
SQLAlchemy factory в spawned child. Worker должен вызывать те же чистые C3 domain functions над snapshot и возвращать
DTO/usage; запись QualityCheckRow/mapping-related events выполняет parent result_hook. Не запускать второй SQLite
и не подменять C3 сервис fixture. HTTP IntelligenceService остается с общей platform session factory.

Оконная поставка: GlassFlow.exe имеет PE subsystem GUI; GlassFlowDiagnostics.exe сохраняет stdout для CLI/official validator.
Multiprocessing запускает GUI EXE, поэтому worker не открывает консоль; exporter запускает diagnostics скрыто.
Первый демо-import доступен POST /datasets/demo, использует семь исходных файлов, сохраняет SHA/bytes и dedupe.
Существующие final PDF защищены от перезаписи: новый выпуск — новый output directory.

## Финальная платформенная evidence

Runtime build `0457954`: expanded frozen smoke PASS на Windows10 build machine, отчет `frozen-smoke.json`.
Проверены GUI PE header, скрытый native worker, singleton, импорт реальных семи файлов, CRM CSV download,
перезапуск, settings persistence, backup/restore. Первый запуск3109ms, повтор3141ms, после restore3078ms.
Скачанный picks.csv проверен неизмененным organizer evaluator: precision0.80, open10/10; closed неизвестен.
Official cutting CLI отдельно проверен synthetic all-NEW **только на формат**, не solver acceptance.
Release scanner PASS. Benchmark samples/machine/inputs в `platform-benchmark.json`.

CI Linux verify прошел на `0457954`; Windows tests/build/поведение smoke также прошли, но вывод финального
отчета упал на cp1252. `768c89c` исправляет переносимый вывод; UTF-8 JSON evidence остается без потери кириллицы.
Последующий статус remote runner фиксируется в status. Ни build-machine smoke, ни fixtures не заменяют
clean Windows/UI/whole-product/live-provider приемку. Последующие commits выполнены от Mustiks07.

Подтвержден итоговый [remote CI run46043713770](https://github.com/Mustiks07/GlassFlow/actions/runs/46043713770)
на `768c89c`: **SUCCESS** Linux verify и Windows-platform, включая expanded EXE smoke, scanner и upload artifact.
После этого изменены только evidence/status/handoff. Runtime и generated contracts не изменялись.

# POST_PLATFORM — N02/N05/N06

База5648852, worktree GlassFlow-post-platform, branch codex/post-platform. Новые функции не переписывают R/T.

## DTO freeze N05/N06

`contracts/labor.py`: LaborStudyCreate/View/Export, MeasurementStart/Action/Finish/Attest, WorkflowQueue/Item.
Все mutations workspace, expected_version исследования и Idempotency-Key; отдельные методы finish и attest.
POST /labor-studies; GET list/get; POST /{study_id}/measurements start; POST /measurements/{id}/pause,resume,finish,attest;
GET /labor-studies/{id}/export. Цепочка событий с hashes, неизменяемое human attestation, elapsed/running/active отдельно.
Рестарт обнаруживается по process epoch, требует явного acknowledge+note; прошедший интервал не становится активным.
Парность task/input/operator/order проверяется, повтор одного способа не перезаписывает данные. U07 export требует10 полных
разных human-attested пар, отрицательное saved время сохраняется. Запись человека не является независимой проверкой истины.

GET /workflow/queue?dataset_id возвращает current canonical blockers, роль и одно следующее действие; read-only проекция.
Смена C2/C3 источника определяется capture/facts_hash, без записи новой бизнес-state или мутации заказа на GET.

Проверено `uv sync --locked --all-groups`; `uv run pytest tests/platform/test_post_labor_workflow.py -o addopts='' -q`:
4 PASS; `uv run ruff check` измененных файлов PASS. Данные времени в тестах synthetic, это не реальные10 замеров.
Реальные трудозамеры требуют человека и пока NOT RUN. Новых таблиц/миграций нет.

## N02: runtime и обязательная интеграция

Ранний DTO commit `ac597a21a36df6a32b098bd84c3d9ad3779644e9`: необязательный
RunRequest.total_budget_seconds (10..7200), export_reserve_seconds (1..600, reserve+5 < total);
RunView.version/budget; Job.accepted_row_count; POST /runs/{id}/budget с RunBudgetRenew,
expected_version и Idempotency-Key. Новый бюджет явный; retry с истекшим бюджетом получает409.
UTC deadline хранится в БД, monotonic применяется только внутри процесса. Старые запросы без бюджета совместимы.

Opt-in полный прогон сначала делает короткий валидный baseline и автоматически сохраняет5 CSV существующим
exporter/official validator; только после принятого комплекта разрешено улучшение cutting. Тяжелая проверка
в отдельном background task, вне DB writer и coordinator loop. Fence по budget generation/attempt/deadline,
частичный/поздний экспорт не заменяет accepted refs. Худший/equal кандидат не продвигается вместо baseline.
Одна improvement попытка на явный бюджет, карточки связаны с выбранным cutting job.

**Root wiring:** перед Coordinator.start() передать `export_context={"data_dir": data_dir, "services": services}`
в main.py. В HTTP /runs и retry есть configuration fallback, но startup binding необходим для restart recovery.
Root делает общую миграцию0006 с immutable UPDATE/DELETE triggers для ObjectRow kind job_checkpoint.
Новых таблиц здесь нет, core/models.py не менялся; system.py/SCHEMA_HEAD принадлежат root.

Принятые assistant rows проходят независимый parent replay через существующий verifier и канонические pricing
tools. Нет второго pricing/verifier и нет доверия произвольному serialized FactSet. Handler.checkpoint_validate,
ProcessContext.checkpoint(row_id,fingerprint,payload), snapshot.accepted_rows; append-only ObjectRow и audit.
Fingerprint закрепляет dataset/точный input/ID/text, KB/material bytes, model/config, prompt/tools/verifier/runtime.
Inventory:none физически отключен для batch; inventory evidence/find_remnants отвергается parent policy.
Late worker не меняет новую attempt. При restart/retry валидные строки перечитываются в исходном порядке;
полный answers результат публикуется только при наличии всех parent-accepted строк.
Provenance различает deterministic, model/LLM tools, cache, fallback и checkpoint_reuse с исходным source_path.
429/error metadata сохраняется только как sanitized kind/status, без текста исключения/ключей.

N15 audit: job.valid_incumbent после parent validation, result_digest с дедупликацией одинакового результата,
фактические metrics и monotonic elapsed с dispatch, без placements. job.stopped содержит реальный stop state/error;
при restart старого процесса elapsed=null, не выдуманный интервал.

## N05 дополнение и BasisWeb DTO

Экспорт/готовность требуют минимум10 разных полных пар и обе очередности manual_first/app_first.
order_counts/protocol_warnings доступны UI. Неподтвержденная лишняя пара блокирует итоговый export_ready;
отрицательная экономия остается отрицательной. rework_seconds описывает часть active, второй раз не суммируется.
Observer/operator и human_confirmed сохраняются; active<=elapsed, прерывание требует подтверждения с заметкой.

По запросу root в ac597a2 добавлены provider=basisweb, included_quota_enabled=false,
quota_token_budget=1000000 (1..5000000). paid_enabled остается false; реальный adapter/ключ у root/Intelligence.
Платные/внешние AI вызовы этим агентом не делались.

## Проверки и пределы

`uv sync --locked --all-groups` PASS. `uv run ruff check backend tests scripts` PASS;
`uv run python scripts/check_foundation.py` PASS:14 immutable inputs,66 requirements,67 assigned scenarios,
точное specification PDF. Полный `uv run pytest tests/platform tests/integration -q -o addopts=''`:
**101 PASS**,165.02s. После него exact input_source_hashes, restore context и queued-stop audit покрыты
заключительным целевым повтором: `uv run pytest tests/platform/test_post_budget_checkpoints.py
tests/platform/test_post_labor_workflow.py tests/platform/test_system.py -q -o addopts=''` — **15 PASS**,35.02s.
JUnit: tests/platform/evidence/post-platform.xml и post-platform-final-targeted.xml. Один warning —
установленная Starlette рекомендует httpx2 вместо httpx в TestClient; проверку не отключали.
Контрактные/доменные сценарии используют настоящие
C2/C3/pricing/официальный validator и durable SQLite, транспорт TestClient; fault injection помечен synthetic.
Это не browser/EXE acceptance и не реальная online AI evaluation.

Новые13 предметных тестов: partial accepted rows+restart+retry, late worker/cancel, KB/model/input invalidation,
trusted pricing replay, real AssistantEngine с scripted429 и provenance, UTC expiry без продления,
auto-first full5 CSV до enhancement, late budget export fence, explicit/idempotent renewal, failed restore recovery,
human active/elapsed/pause/negative pairs/mismatch/interruption, canonical workflow без state writes.
Фактические человеческие10 пар, чистая Windows, browser E2E, EXE и живой AI экзамен — NOT RUN этим пакетом;
финальная интеграция/проверка и main/push выполняются root. Общие generated contracts перегенерирует root.

Следующий шаг root: объединить codex/post-platform, подключить startup export_context, миграцию0006,
перегенерировать общие схемы, затем проверить настоящий HTTP/browser/EXE и ограниченный live AI.

## N01 реальное соединение (следующая задача root)

Перед работой merged codex/post-integration-upgrades на9b4247f (C2 sale_readiness/scarcity/NEW и Intelligence).
Затем merged Intelligence c5fc208, merge63c647a — только их история; авторские файлы не переписывались.

`core/snapshots.sale_readiness_snapshot` получает текущий C2 solve_input, оригинальные source records и
проверенный реестр sales.registry. S вычисляется сервером через настоящий match_buyers: минимум3 разных
объяснимых организаций; размеры/материал должны совпадать с оригиналом для полной карточки. Текущие резервы,
occupied/status/nonoriginal исключаются; committed baseline сохраняет собственные reservations/placement locks.
Fingerprint содержит весь registry content/version, current inventory, C2 input и matching evidence; клиент S не задаёт.

Полный run с buyer_registry автоматически включает server context; улучшение N02 захватывает свежий context.
Existing cutting handler вызывает C2 ensure_sale_readiness после baseline. Если уже5free eligible — без поиска;
если во всём доступном складе S<5 — evidence_shortage без поиска. Raw C2 incumbents до search допустимы как
pinned geometry-only; final hook требует bundle, повторно читает trusted running Job.input и заново capture current.
Bundle временно JSON string внутри scalar CutPlan.evidence; перед сохранением удаляется. Сохраняются исходные
stop/config/evidence; workers не выдают fake stop provenance. Parent самостоятельно пересчитывает status/free/delta,
геометрию каждого варианта и каноническую площадь через существующий C2 store (без нового geometry/pricing engine).

Baseline сохранён отдельно; zero-area-loss/improving alternative может быть selected с явными refs. Tradeoff
с уменьшением площади — отдельный stored ref, никогда не selected молча. При несогласованном delta/payload все
записи откатываются той же транзакцией. При stale job результат не продвигается, прежний baseline/accepted остаётся.
Standalone существующего плана сохраняет его исходный baseline ref, включая committed с собственными резервами.
Cards получают cutting_result выбранного persisted plan; E2E тест проверяет5cards ×3matches именно этого ref.

**Root standalone route seam:**
`runs.enqueue_sale_readiness(session,dataset_id,baseline_plan_id,baseline_revision,registry_version,*,budget_seconds=2)`
возвращает стандартный job_dto, kind=cutting, run_id=None. Route root владеет session/owner/idempotency/body validation;
ожидание через существующий GET /jobs/{id}. Функция не принимает eligible IDs. Результат содержит typed existing
SaleReadiness в result.sale_readiness и refs baseline_plan_ref,selected_plan_ref,alternative_plan_ref,tradeoff_plan_ref
({plan_id,revision}; optional refs null). Отдельный explicit tradeoff selection root может добавить с новым current
capture; этого автоматического перехода здесь нет. Общих DTO/main/ports/sales/insights edits этим пакетом не сделано.

## N07 accepted batch hook

По отдельному разрешению root payload whitelist включает review_reasons/review_user_text. Причины формирует
Intelligence.outcome_reasons; parent повторно сверяет текст с pinned question и correct_policy/missing_parameter/kb_fact
с каноническим local outcome в уже выполняемой проверке. Historical checkpoints без metadata совместимы и не
переписываются. Новый store_assistant вызывает record_accepted_batch_reviews в той же Session после полного accepted
batch; нет новой engine/network/DB. Root должен зарегистрировать result_hooks['assistant']=store_assistant в composition.
Synthetic regression проверяет правильный policy отказ, отклонение подмены category и полный rollback review inserts.
Provider/verifier причины дополнительно согласованы с accepted llm_status/error metadata; выдуманная provider_error
при deterministic результате отвергается. Основные policy/KB/parameter причины replay проверяются предметно.

Старые isolated Services без cutting handler не имеют C2 registration и сохраняют прежнее dependency-failure
поведение foundation (sale_readiness_enabled=false). Реальная composition включает connection всегда при registry;
никакой fallback eligibility/fixture data для production нет. Форматный fixture-export не объявляет N01 проверенным.

Первые connection12 PASS, включая настоящий spawn/5cards и own committed reservations; до последнего добавленного
forged-delta regression combined connection+budget20 PASS/35.28s. Финальный расширенный повтор записывается ниже.
Ruff всего backend/tests/scripts PASS, foundation14/66/67/PDF PASS. Независимый review oracle не использован.

Финальный N01/N07/регрессии: `uv run pytest tests/platform/test_sale_readiness_connection.py
tests/platform/test_post_budget_checkpoints.py tests/platform/test_jobs.py tests/platform/test_exports.py
-q -o addopts='' --junitxml=.post-sale-final.xml` — **29 PASS**,53.39s. JUnit сохранён в
tests/platform/evidence/post-sale-connection.xml;13 новых connection tests включают forged area/delta rollback,
strip bundle final-hook fence и truthful review categories. Ruff all PASS, diff --check PASS.

Следующий точный шаг root: merge ветку, добавить route к enqueue_sale_readiness и assistant result hook,
схемы/UI для явных plan refs; отдельно выполнить реальные browser/EXE проверки и live AI. Эти тесты не являются
пройденными browser E2E/AI exam. EXE/final human economy этим продолжением не создавались/не заменялись.

## Независимая проверка root N08/N09/N15 на f642c3b

Переданы ownership insights/contracts.insights/tests.insights; root main/composition/frontend не менялись.
Исходный insights suite11 PASS. Найдены и исправлены P1:

- N08 неизвестные M9/M10/имена, даты, неподдерживаемые фильтры и отрицания раньше молча расширяли выборку.
  Теперь finite parser требует уточнение при нераспознанных условиях; source values совпадают целыми словами,
  overlapping values выбираются по полному значению, несколько группировок применяются все. Второй явный
  показатель «число заявок» не игнорируется рядом со средним чеком; «сколько средний чек» остаётся полным вопросом.
- N09 checked basket PDF не содержал кусков/мест. При create document новый snapshot фиксирует current_selection,
  настоящие текущие Remnant DTO, версии, координаты и соответствующие детали. Повторный текущий capture и версии
  проверяются в той же transaction. PDF показывает piece/version/material/dimensions/location/parts, состояние на русском.
  Длинная строка разрешает перенос между страницами (splitInRow),180 частей не теряются.

Не подтвердилось предположение о пустом warehouse_task у confirmed order: orders.project создаёт его на bind/confirm.
Настоящий order → PDF содержит450×370,qty1,актуальный ID/место; после cancel immutable document сохраняется.
Добавлен только безопасный facts fallback для старого document snapshot без task.
Old label resolve возвращает текущую запись, а reserve с printed_version отвергается именно VERSION_CONFLICT;
история/бирка immutable, label никогда не дает capability для мутации.
Новый basket checked API test использует настоящие quote/worker/резерв/check, проверяет PDF/current places,
отсутствие бизнес-перехода при печати, idempotency и отказ новой печати после изменения места; старый документ неизменен.

N15 дефект не обнаружен: настоящий полный run → official validated export (5 result CSV + buyers_top50.csv),
затем второй настоящий cutting worker в том же run. Current passport показывает новый job, accepted passport
остаётся полностью равен прежнему (старые job IDs/metrics/history/refs/hashes/provenance), все скачанные bytes
совпадают с pinned hashes. passports.py не менялся. Старые unit integrity/final-only проверки также PASS.

`uv run pytest tests/insights -q -o addopts='' --basetemp=.qa/insights-acceptance
--junitxml=.post-insights-final.xml` — **28 PASS**,26.60s. После уточнения одного test assertion до точного
VERSION_CONFLICT — отдельный label test **1 PASS**,1.55s. Ruff all и foundation14/66/67/PDF PASS, diff-check PASS.
JUnit: tests/insights/evidence/post-insights-final.xml. PDF skill прочитан, реальные PDFs визуально проверены
через bundled Poppler PNG: .qa/order-final-1.png, .qa/label-final-1.png, .qa/basket-final-1.png;
renderer stress2 pages: .qa/long-final-{1,2}.png. Кириллица/отступы/переносы без потерь; QR видим, аппаратный scanner NOT RUN.
Это API/renderer acceptance на production composition, не browser/EXE/чистая Windows/human measurement acceptance.

## Новый HTTP source / actual failures / restart на554adc1

Новая задача root: frozen isolated branch, TCP uvicorn18484, свежая `.qa/new-inputs`; код продукта не менялся.
`scripts/post_acceptance.py` генерирует отдельные changed inputs, original materials/KB сохраняет побайтно,
не читает KEY/секреты, запускает child без AI credential env и проверяет свободный порт. Backend tree не меняется
между parent source_digest и spawn worker. Реестр — independent-v2,50 организаций.

Полный budget120/reserve30 baseline5/improvement6 autoaccepted8.235s. Скачаны5 resultCSV+buyers_top50;
проверены exact headers, noBOM/UTF8, все новые ID/counts, unique25 picks,5 cards×3 explainable actual matches,
manifest hashes. Original validator на скачанных bytes coverage0.558090,invalid0,missing0,165/298,960705₸ replacement
value. Это другой вход, не сравнение с исходным open score и не прибыль. На новые questions/dialogs нет KEY:
official hidden accuracy/live AI NOT RUN.

Реальное deadline source1000questions: 12s total/4 reserve -> RUN_WORK_BUDGET_EXCEEDED,100 принятых durable rows,
partial export без полного answers. Дополнительный real cancellation:4 других modules completed, assistant cancelled
после256 accepted rows; partial export содержит4 result CSV+buyers, answers отсутствует. Это фактические API события,
без инъекции JobRow/fixture worker/подмены доменных портов. Дополнительная cancellation duration не записывалась.
После остановки coordinator/uvicorn и рестарта sameDB accepted passport unchanged, old artifact hashes unchanged,
existing partial accepted_row_count сохранился. Новый dependency cards job мог появиться после раннего poll;
проверяется сохранность существующих job counts, не ошибочное равенство состава очереди во времени.

**Общий статус blocked_product_issue**: explicit unknown ZETA SKU ошибочно стал known hanger price400/200₸
(`answered/supported`, deterministic,0modelcalls). Root/Intelligence получили точный witness. Проверка не ослаблена:
финальный harness exits2 при незакрытом issue, независимые этапы продолжают собирать evidence.
Report/source/downloads: docs/release/post/http-new-inputs, README содержит exact reproduction/new fresh path.
Первый harness cards URL исправлен с nonexistent /cards/{id} на реальный /sale-cards + pinned exported refs;
это ошибка проверяющего, не исправление продукта. Публичный source/case/final materials не менялись.
Следующий шаг: дождаться Intelligence fixed SHA, merge на остановленной isolated ветке, новый fresh полный TCP run
и строго повторить unknown probe; прежний blocked report сохранить отдельно. Затем root final EXE/browser/release.

## N02 terminal dependency replay P1

Fresh actual HTTP failure на общей базе2c6afcc выявил17 failed cards одного terminal cutting attempt.
Причина: budget scheduler записывал failed dependency с input={} и на каждом tick воспринимал его как другую
cutting revision. По отдельному разрешению root только runs.py: failed card теперь хранит cutting_job_id.
История не удаляется; новая явная попытка cutting получает ровно один свой dependency result.
`uv run pytest tests/post_acceptance/test_dependency_replay.py tests/platform/test_post_budget_checkpoints.py
-q -o addopts=''` — **10 PASS**,30.40s, scoped Ruff PASS. Regression проверяет8ticks,2coordinator restarts,
и отдельную следующую попытку. Минимальный product commit отделён от HTTP artifacts/harness.

## Финальный changed-input HTTP acceptance PASS

Frozen runtime4ee5812a65157acd7aa504df3d994497f608e29a = root55049e4 + C3efbf8de + f090a75.
`uv run python scripts/post_acceptance.py --data .qa/new-inputs-release-final
--output docs/release/post/http-new-inputs-final` — exit0, **PASS**,53.922s whole observer;
first full autoaccepted9.781s within120/30 reserve. Actual improvement job completed, not promoted,
baseline preserved. Unknown exact ZETA phrase manager_handoff,0modelcalls,no pricefacts/sums/readyquote;
product_issues=[]. Original strict wording retained.

Downloaded5 exact resultCSV+buyers50, original immutable validator coverage0.558090/invalid0/missing0,
165/298,960705₸ replacement valuation on changed inputs (не исходный open score/не прибыль).
5cards×3actual evidence matches. Actual deadline persisted150acceptedrows; separate APIcancel persisted300
with4otherjobs complete. Quality's explicit unknown-SKU dialog remains unresolved, UNRESOLVED_VERDICT:
partial export contains3resultCSV+buyers, answers AND verdicts withheld. Dependency failed-card ID stable on ticks+restart.
SameDB actual owned uvicorn process-tree restart preserved identical accepted passport, all old download hashes,
150partial rowcounts and dependency ID. No API key/model/evaluation KEY/fixture port/DB mutation.

Harness fixes only: real /sale-cards endpoint; durability queries each historical job by ID rather than latest-per-kind;
Windows venv redirector host stopped by owned Popen PID tree after API coordinator stop, not process-name matching.
Intermediate harness failures saved in ignored QA, current final report is a fresh complete one-pass invocation.
Production P1 fixes remain separate commits: C3 unknown identity guard and f090a75 terminal dependency replay.
Artifacts, exact reproduction and limitations: docs/release/post/http-new-inputs-final; post/README distinguishes
historical blocked witness. All artifact bytes protected by scoped post/.gitattributes. Root owns final CI/EXE/browser/
online AI/human/clean-Windows acceptance and main/push; none of those are inferred from this local HTTP PASS.

## N02 next-tick pending race (independent review)

Root reviewer на immutable92aed19 зафиксировал4completed non-card jobs до schedule_cards: RunView ошибочно
возвращал partial, frontend прекращал poll. Аналогичное окно accepted baseline -> next tick improvement позволяло
кратковременный completed до реально ожидаемого improvement dispatch.
По отдельной передаче ownership исправлен только runs.py: cards_dispatch_due/improvement_dispatch_due — общие
малые predicates view и scheduler. View ждёт реально планируемые cards после completed cutting при живом work
budget; ожидаемый improvement только при accepted export, nonquick time>5s, work>7s и отсутствии попытки.
После recorded completed/failed/cancelled attempt, quick/too-short config или истечения work budget running не
удерживается. Accepted refs/files не изменяются. No-budget baseline cards также не теряются до первого tick.
Terminal failed/exhausted cards остаются partial; dedup dependency fix сохранён.

`uv run pytest tests/post_acceptance tests/platform/test_post_budget_checkpoints.py tests/platform/test_jobs.py
-q -o addopts=''` —25 PASS/38.66s. После дешёвого early-return для no-budget/no-accepted в scheduler:
`uv run pytest tests/post_acceptance -q -o addopts=''` —13 PASS/6.09s, Ruff scoped PASS.
Следующий шаг: новый fresh полный TCP acceptance с этим минимальным product commit; прежний4ee5812 PASS
сохраняется как evidence предыдущей базы, не объявляется проверкой нового guard.

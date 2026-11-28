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

# U04/U06: платформенный контракт

План v1.1 прочитан из main24049e1. Это дополнения, не изменение66R/67T.
Pro публикует контракт перед зависимой реализацией. Python DTO — `contracts/baskets.py`, `material_use.py`;
существующие C3 QuoteRequest/Quote и U01 ownership используются без копирования коммерческих правил.

## U04: корзина целиком

Новый `basket_id` в workspace, стабильные `line_id`, `version` для каждой записи и `revision` для изменения
состава/привязки фактов. История полных snapshots в immutable audit_events. U01 single-order routes сохранены.
Состояния: draft/needs_review/ready/confirmed/reserved/checked/handed_over/completed/stale/cancelled.
Неизвестная строка имеет request=null/clarification; цена не становится0. total=null, если хотя бы одна
строка не готова; known_subtotal — отдельная сумма известных canonical line totals, не сумма заказа.
Количество/размеры/selected processing sides хранятся в canonical C3 QuoteRequest каждой строки.
Pro только складывает готовые Quote.total_tg, **не умножает на quantity повторно** и не рассчитывает кромку.

HTTP `/api/v1/baskets`: create/list/get/history, POST /{id}/lines, /bind, /confirm, /reserve,
/warehouse-check, /handover, /release, /cancel. Mutations: expected_version/operator/note, Idempotency-Key.
Parser warnings хранятся отдельно в review_warnings и не исчезают при bind готовых quotes. Они блокируют total/confirm,
пока менеджер явно не проверит/уточнит строки через /lines (с оператором/заметкой). Все прежние warnings остаются в history.
Новый bind после release очищает старый reservation reference; история старого резерва сохраняется.
Изменение строк требует снятия активного резерва и сбрасывает факты; stale не подтверждается без explicit bind.
Каталожная корзина без glass не заявляет резерв материала: stock/reservation=null.

`Services.basket_source: BasketSourcePort`, вызывается в коротком caller Session, без network/solver/commit:

1. capture(session,basket,binding) -> BasketFacts. Прочитать CURRENT C3 quotes, их владельца,
   source_request_hash и одну CURRENT совместную selection C2. Не копировать customer/validated/hash из запроса
   как доказательство. Для каждой строки source_request_hash — SHA canonical JSON **сохраненного QuoteRequest**.
   input_hash — SHA `{customer_ref,request_text,lines}` сохраненного входа, соответствующего joint selection.
2. BasketFacts.lines обязаны покрывать ровно все line_ids, без повторов. Quote IDs/revisions принадлежат
   соответствующим строкам. Customer каждого quote подтвержден как в PRO-U01-F1. Compatibility fittings — C3,
   needs_review блокирует всю корзину. Unknown/partial не отбрасывается при confirm.
3. BasketStockFacts покрывает ровно glass line_ids; selection_ref/version, validation_ref, validated,
   remnant_versions и planned area/value берутся из C2. Это **одна joint validation** с учетом quantity/общих
   кусков, не сумма независимо подобранных кандидатов. Pro геометрию/емкость не дублирует.
4. reserve(session,basket) -> BasketReservation: сравнить pinned facts и зарезервировать **все** в одной transaction.
   C2 гарантирует единственное владение во всех API/заказах/корзинах и корректный совместный расход одного куска.
   Возвращает post-reserve remnant_versions. capture после собственного reserve меняет только эти версии,
   не цены/selection/input/владельца; mismatch откатывает весь резерв. Даже all-NEW selection может иметь
   canonical aggregate reservation с пустым remnant_versions; Pro ее не придумывает.
5. reservation/release читают canonical владельца и атомарно снимают весь bundle. Ошибка второй строки
   откатывает первую; нет тихого partial success. Резерв/отмена не создают material usage.

Heavy parsing выполняется через общую очередь `basket.parse`, Handler lane=network, без SQLite в child.
Неразобранный фрагмент должен остаться unresolved строкой с clarification, а не исчезнуть из результата C3.
POST /{id}/parse возвращает Job202, если C3 handler зарегистрирован; иначе503. Payload:
dataset_id,basket_id,basket_version,input_hash,customer_ref,request_text,KB bytes JSON+version,AI settings;
credentials только private_context. Result — BasketParseResult. POST /{id}/apply-parse с job_id применяет
весь результат явно после проверки scope/version/hash; старый/чужой результат не перезаписывает правки.
Ошибки/cancel/retry/restart — существующие durable jobs. Quote/selection тяжелые расчеты создаются обычными
C3/C2 domain jobs до /bind; capture только читает артефакты. Без порта503, production fallback нет.
При вызове портов Pro передает и принимает detached deep snapshots: мутация DTO адаптером не меняет
оригинал, с которым сравнивается возвращенный результат/квитанция. Сами canonical artifacts по-прежнему в C2/C3.

## U06: подтвержденный расход

HTTP POST `/api/v1/material-use`, GET list/summary/by-id. Body MaterialUseRequest: subject_type order/basket,
POST /preview возвращает read-only assessment до человеческого подтверждения, не вызывает confirm/consume.
subject_id, expected_version, execution_ref/version, operator,note,discrepancy_reason. Это refs canonical C2
**фактического исполнения**, не денежные суммы/геометрия из браузера. Требуется handed_over и active reservation.
Ни reserve, ни cancel, ни сам handover не создают usage; до явного подтверждения summary.actual=0.

`Services.material_use: MaterialUsePort`, тот же caller Session:

- assess(session,MaterialUseScope,execution_ref,execution_version) -> MaterialUseAssessment: прочитать canonical
  actual execution, проверить dataset/subject/revision/reservation owner/expected inventory versions, вернуть
  independently validated planned/actual area/value, validation_ref/material_price_version. Не echo входа как proof.
  Исполнение должно быть окончательным для всего material reservation; partial/in-progress не подходит для confirm.
- confirm(session,assessment,confirmation_id,operator,note) -> MaterialUseReceipt: compare-and-consume атомарно,
  с durable token confirmation_id и уникальным source_event_ref. Вернуть точно assessment, consumed и post versions.
  Post version каждого затронутого куска строго больше версии в reservation scope; чужие/пропущенные IDs запрещены.
  Все пути C2 обязаны защищать event/reservation от повторного списания, в том числе вне Pro UI.

Pro проверяет receipt scope и assessment до записи ledger. Расхождение planned/actual area/value требует причины.
Ledger immutable на уровне SQLite; уникальны subject, reservation и canonical source event внутри dataset.
Повтор с другим Idempotency-Key того же execution возвращает исходную запись без вызова C2. Другое execution
для уже учтенного subject —409, не новая сумма. Receipt validation/DB unique failure откатывает C2 mutation.
Успех переводит subject в completed и сохраняет usage_id; ledger+subject+audit+idempotency в одной transaction.
Редактирование/удаление ledger и переучет completed subject не разрешены. Исправление физического события
потребует отдельного future correction contract C2, не переписывания истории SQL.
Schema head `0003_material_use` следует за0002; pre-migration backup обязателен и проверен тестом.
U01 OrderSheet получает lifecycle=completed/material_use_id; после usage текущие offer/warehouse forms скрыты,
исторические подтвержденные документы сохранены. Catalog-only без material reservation не создает расхода материала.
completed здесь означает завершенный material workflow, не оплату или подтвержденную доставку клиенту.

Summary planned/actual area/value показывает раздельно, с usage IDs/source events. Это оценка использованного
материала, не прибыль/выручка/продажа. U07 получает ее как отдельную evidence-ссылку; planned+actual и gross+delta
не складываются как две выгоды. Ни buyer cards, ни CRM, ни конкурсные CSV не меняются от confirmation.

C1: таблица строк/уточнения/итог=null, подтверждение **всей** корзины, warehouse note, явная кнопка actual use
с execution ref и причиной расхождения; повтор показывает исходное подтверждение. C2/C3: реализовать эти порты
на общей БД и parent transaction; C1/C2/C3 E2E приемка остается not_run до подключения. Test adapters — только tests.

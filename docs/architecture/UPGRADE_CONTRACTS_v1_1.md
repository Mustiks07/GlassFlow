# Дополнения v1.1: контракт платформы

Источник: plan v1.1 из main `eaf81d6`. Это добавление, не изменение 66R/67T.
Контракт объявлен Pro до реализации зависимых частей. Canonical Python DTO:
`backend/glassflow/contracts/orders.py`; OpenAPI/TS регенерируются стандартно.

## U01: один лист заказа, две формы

`OrderSheet.order_id` — новый рабочий ID, не подмена исторического order_id исходного CSV.
Только dataset mode workspace. `version` растет при каждой записи, `revision` — при привязке
новых фактов расчета/куска. Каждая запись сохраняет полный snapshot в append-only audit_events.
Старое подтвержденное предложение остается в истории после нового замера. GET/history доступны после рестарта.

Независимые состояния: quote missing/draft/confirmed/stale; warehouse unchecked/checked/handed_over/stale;
lifecycle open/handed_over/cancelled. Резерв — ссылка на C2 (active/released/consumed), а не вторая inventory.
Подтверждение расчета, резерв и человеческая проверка склада — разные команды.
Подтверждение оператора является записью человека, не доказательством датчика или отправки клиенту.

`OrderOffer` и `WarehouseTask` рендерятся из одного `OrderFacts`/facts_hash/revision.
Offer содержит canonical C3 Quote, warehouse — canonical C2 Remnant + requested dimensions/quantity.
Неизвестное место остается пустым с location_known=false. Stale лист не выдает действующее предложение/задание.
Ни цена, ни совместимость, ни координаты не вычисляются в платформе.

Регистрация: `Services.order_source: OrderSourcePort` (см. ports.py), реализует интегратор из C2/C3:

- capture(session,dataset_id,quote_id,remnant_id,order_id) -> current OrderFacts:
  C3 quote/revision/KB/mapping + C2 remnant/version/compatibility/alternatives.
  C3 должен возвращать ready/confirmed, preliminary=false, material_mapping_status=confirmed для confirm.
  Изменение KB, mapping, замера или статуса наличия должно отражаться в текущих фактах.
- reserve(session,facts,order_id,order_revision) -> OrderReservation: сравнить текущую версию и атомарно
  резервировать в **той же** SQLite transaction. Уникальное владение исходным куском обеспечивает C2.
  Вернуть post-mutation version. Capture после reserve должен учитывать владельца и не инвалидировать
  предложение только из-за собственного резерва. Чужой резерв — конфликт409 с текущей версией/альтернативой.
- reservation(session,dataset_id,reservation_id): текущее состояние, exact owner/revision/version.
- release(session,reservation): compare-and-release; rollback платформы откатывает C2 mutation.

Порты не делают commit/network, не создают второй Session/DB. Без порта bind/confirm/reserve дают503,
черновик/история доступны. Только explicit fixtures в тестах; production fallback отсутствует.

HTTP под `/api/v1/order-sheets`: POST create; GET list; GET /{id}; GET /{id}/history;
POST /{id}/bind, /confirm, /reserve, /warehouse-check, /handover, /release, /cancel, /reminder.
Mutation body OrderAction (dataset_id,expected_version,operator,note), bind добавляет exact quote/remnant revisions.
Все mutations требуют Idempotency-Key; повтор запроса возвращает прежнюю запись и не резервирует повторно.
При смене источника recheck сохраняет stale и команда возвращает409; старые документы в history неизменны.
Reminder link принимает только существующее актуальное quote_example этого customer/quote/revision.
C1 использует offer/warehouse_task, показывает состояния и stale, не вычисляет денежные поля в браузере.

U03 и U07 контракты будут дописаны перед соответствующей реализацией. U02 остается владением C3.

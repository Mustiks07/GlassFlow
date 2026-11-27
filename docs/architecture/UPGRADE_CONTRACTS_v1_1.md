# Дополнения v1.1: контракт платформы

Контракты следующего уровня U04/U06: [U04_U06_CONTRACTS.md](U04_U06_CONTRACTS.md).

Источник: plan v1.1 из main `eaf81d6`. Это добавление, не изменение 66R/67T.
Контракт объявлен Pro до реализации зависимых частей. Canonical Python DTO:
`backend/glassflow/contracts/orders.py`; OpenAPI/TS регенерируются стандартно.

## A04: выбранный снимок экспорта

CSV bytes, result_refs и module_provenance фиксируются в одной короткой transaction до external validator.
После него latest_jobs не читается. Result refs относятся к выбранным jobs, даже если новый job уже завершился.
Следующий export может выбрать его. `last_export_id/files` описывают последнюю попытку, в том числе partial;
`accepted_export_id/accepted_files` меняются только после полного ready (все5 CSV + buyers, все проверки).
Partial/blocked retry не убирает ссылку на ранее принятый комплект. Старые export directories неизменны и доступны.

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

### PRO-U01-F1: принадлежность расчета

`OrderFacts.quote_customer_ref` — клиент **сохраненного расчета C3**, прочитанный capture в том же Session.
Это поле заполняет canonical adapter из quote repository; его нельзя копировать из OrderSheet.customer_ref,
запроса bind, текущего менеджера или источника reminder. Bind не принимает клиентское утверждение о владельце.
Если объединенный C3 Quote имеет `customer_id`, он должен точно совпадать с quote_customer_ref.
Все три идентификатора — customer_ref листа, quote_customer_ref и (если есть) Quote.customer_id — согласованы.

- Известный чужой клиент ->409 QUOTE_CUSTOMER_MISMATCH до bind/confirm/reserve.
- Нет подтвержденного владельца (null/legacy missing) ->409 QUOTE_CUSTOMER_REQUIRED.
- Противоречие explicit attestation и Quote.customer_id ->409 QUOTE_CUSTOMER_INCONSISTENT.

Анонимный расчет остается самостоятельным черновиком C3; заказ можно создать без привязанного расчета.
Для binding сначала требуется **явное** назначение клиента в C3 либо новый расчет нужного клиента.
Платформа не присваивает anonymous quote автоматически и не переписывает клиента чужого расчета.
Ownership включен в facts_hash. Перед confirm/reserve/warehouse-check/handover выполняется current capture;
изменение принадлежности сохраняет durable stale, stale_code и историю, текущие формы скрываются.
Уже сохраненная неизвестная принадлежность не восстанавливается автоматически из клиента заказа: explicit rebind.
Для разрешения конфликта нужен корректный расчет и новый bind; если есть активный резерв, сначала explicit release.
Историческое подтвержденное предложение сохраняется как snapshot прежнего события, не как текущая готовность.
Post-reserve capture также проверяет клиента: конфликт откатывает C2 mutation и платформу в одной transaction.
Idempotent replay — сохраненный результат прежней команды; текущая готовность читается через GET/recheck.
После merge повторить на actual C3 quote repository/C2 reservation service, без копирования правил C3 в Pro.

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

## U03: объяснимый подбор

C1 передает дополнительный `applications: BuyerApplicationEvidence[]` в каждой evidence.records организации.
Исходный buyers CSV не меняется. Поля: application (furniture_insert/mirror_interior/display_insert/
partition_panel/finished_panel), material_ids (явные canonical ID из materials), min_dimensions,
max_dimensions (optional), requires_cutting, dimensions_basis, activity, source_url, checked_at.
activity — публично подтвержденная деятельность; dimensions_basis — явное основание/допущение размера,
а не выдуманная потребность. Source URL/date проверяются импортером по reviewer evidence.
Имена/даты/профиль без applications по-прежнему импортируются, но сами по себе не объясняют пригодность.

`GET /buyers/matches?dataset_id=&version=&remnant_id=` берет **current** C2 Remnant и current material.
Возвращает BuyerMatch[] с ID/точным именем/registry/remnant versions, материалом/размером,
публичной деятельностью, source URL/date, применением/ограничениями и interest_confirmed=false.
Подбор детерминированный, без ML/LLM, учитывает обе ориентации size bounds и дефект.
Для tempered запрещен requires_cutting=true; готовый исходный размер указывается явно.
Defect не скрывается. Ни score, ни совпадение слов в why/category не заменяют material/size evidence.

Новые SaleCard содержат три buyer_matches, matching_policy=evidence-v1 и match_snapshot_hash.
Generate использует только целые актуальные свободные originals выбранного C2 plan; если нет пяти кусков
с тремя пригодными покупателями, явный409 вместо произвольных имен. Edit top3 допускает только текущие matches.
Recheck/export повторно проверяют match snapshot, C2 status/version и registry; старые unexplained cards требуют regenerate.
C3 может формулировать только из этих BuyerMatch; source факт покупки/согласия не содержит.
Смена материала означает новый current remnant/version и новый подбор; старые explanations не переносятся.

## U07: одна формула экрана и PDF

DTO `contracts/economics.py`. POST `/economics/scenarios` принимает EconomicsCreate; PUT /{id} принимает
EconomicsUpdate с expected_version и Idempotency-Key. GET /{id}?dataset_id=&version= возвращает точный snapshot;
GET /{id}/pdf?dataset_id=&version= рендерит этот же snapshot. Исторические версии сохраняются в append-only audit.
C1 меняет inputs, берет decimal-string results с backend; формулу в JS не дублировать. В PDF те же input_hash,
result_hash и formula_version=economics-v2. Платформа не отправляет документы клиенту/организаторам.

LaborStudy: минимум10 уникальных задач, одинаковые start/end definitions и input_ref для ручного/app выполнения,
operator/observer, timezone start/end timestamps, active seconds (включая rework), ошибки/rework и result refs.
measurement_status=supplied_measurements — декларация источника пользователя, не автоматическая независимая проверка;
synthetic явно помечается. Без настоящих замеров финальная конкурсная записка остается blocked.

Material effect=(final-baseline)*monthly multiplier*material_use_fraction. Валовая оценка плана не прибавляется
еще раз. Fraction — явное scenario assumption с basis; actual confirmed-use value+ref отдельны.
Potential remnant sale и actual sale revenue+ref тоже отдельны и не включаются как прибыль в net.
Labor effect=median paired saved seconds/3600*monthly_operations*hourly_rate.
Net=material effect+labor-services. Payback только net>0. Sensitivity задает low/high для4 assumptions,
показывается min/max углов плюс измеренный разброс парной экономии, не доверительный интервал.
Операционные факты и плановые оценки не смешиваются; no-payback scenario обязателен.

HTTP PDF — «сценарный расчет, не финальная конкурсная записка», competition_release_eligible=false.
Финальная записка по-прежнему требует same-run ready manifest и actual labor evidence через release builder.
U02 остается владением C3; исходные трудозамеры делает человек, Pro их не синтезирует для приемки.

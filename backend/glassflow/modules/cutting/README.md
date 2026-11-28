# Модуль cutting: склад, геометрия, раскрой, резервы

Владелец: Клауд второй (Мырзабек). Ветка `codex/claude-2-myrzabek-cutting`. Статус и доказательства —
`docs/status/CLAUDE_2_MYRZABEK.md`.

## Структура

| Файл | Назначение |
|---|---|
| `domain.py` | Чистые frozen-dataclass сущности (целые мм, `Decimal`), константы `TRIM_MM=5`, `GAP_MM=3`, `TEMPERED_TOLERANCE_MM=2`, `NEW` |
| `geometry.py` | Независимый строгий валидатор (`validate_plan`), строгий парсер `solution.csv` (`parse_solution_rows`) |
| `eligibility.py` | Граф допустимости деталь→кусок с кодами отказа |
| `packing.py` | MaxRects / Guillotine в «раздутых» координатах (точная редукция зазора и отступа) |
| `solver.py` | Портфель: matching калёного (венгерский алгоритм), жадные Guillotine/MaxRects, пул шаблонов, SciPy `milp` (HiGHS) с условием ≥5 свободных исходных кусков, column generation (LP-дуалы → эвристики и точный CP-SAT pricing), CP-SAT LNS, лексикографическая фаза |
| `engine.py` | `CuttingEngine` — реализация `glassflow.ports.CuttingPort` для worker; `CuttingPortAdapter` для внутрипроцессных потребителей (AI tools, sales) |
| `metrics.py` | Метрики только по валидированным размещениям; оценка материала `Decimal` |
| `models.py` | Таблицы `cut_*` на общем `Base` |
| `service.py` | `CuttingService(session)` — склад, планы, редактор, атомарный commit, резервы, расход, сравнение, влияние, быстрый подбор, события |
| `router.py` | HTTP `/api/v1/...` |
| `uow.py` | Временные границы транзакции до UoW от Pro |
| `source_io.py` | Строгое чтение CSV организаторов и запись точного `solution.csv` |
| `cli.py` | Доказательный прогон с неизмененным `validate.py`, загрузка набора в локальную БД |
| `migrations/` | Генератор DDL и снимок `0001_cutting.sql` для единой истории Alembic |

## Правила геометрии (совпадают с validate.py и строже)

rot=0: длина детали по x (длина остатка), ширина по y; rot=1 — наоборот. Обычное стекло: `x≥5, y≥5,
x+w≤L−5, y+h≤W−5`, для каждой пары хотя бы одно осевое разделение ≥3 мм (касание на 3 мм допустимо).
Premium запрещен на `defect=1`. temp-4/temp-6: одна целая деталь, каждый размер ±2 мм в одной
ориентации, без обрези; экспорт `x=0,y=0,rot=<совпадающая ориентация>`, пустые координаты тоже принимаются.
Дополнительно: полнота и уникальность part_id, неизвестные детали/остатки/материалы, недоступность куска,
закрепления, строгие целые значения, NEW без координат.

Коды ошибок валидатора: `DUPLICATE_PART, MISSING_PART, UNKNOWN_PART, UNKNOWN_REMNANT, UNKNOWN_MATERIAL,
REMNANT_UNAVAILABLE, MATERIAL_MISMATCH, PREMIUM_ON_DEFECT, TEMPERED_SIZE_MISMATCH, TEMPERED_MULTIPLE_PARTS,
TEMPERED_BAD_COORDINATES, MISSING_COORDINATES, NON_INTEGER_VALUE, NEGATIVE_VALUE, INVALID_ROTATION,
OUT_OF_BOUNDS, GAP_VIOLATION, OVERLAP, NEW_WITH_COORDINATES, LOCK_VIOLATED, EMPTY_FIELD`.
Каждая ошибка: `code, message_ru, part_id, remnant_id, other_part_id, coordinates`.

Причины NEW / отказа подбора: `MATERIAL_MISMATCH, UNKNOWN_MATERIAL, PREMIUM_ON_DEFECT, SIZE_TOO_LARGE,
TEMPERED_SIZE_MISMATCH, REMNANT_UNAVAILABLE, OCCUPIED, LOCK_CONFLICT, LIMITED_SEARCH,
NO_COMPATIBLE_REMNANT, INSUFFICIENT_JOINT_CAPACITY`. `LIMITED_SEARCH` — поиск не нашел места за лимит,
не доказательство невозможности. Каталожный `unmapped` — не код раскроя (это каталог C3).

## Профили и статусы

| Профиль | Состав | Цель |
|---|---|---|
| `quick` | matching + 24 жадных порядка | первый валидный план ≤5 с |
| `standard` | + пул, MILP, column generation, CP-SAT | 60 с |
| `extended` | больше пула и раундов CP-SAT/LNS, терпение 12 раундов | 600 с, конкурсный |

`fixed_work=true` — однопоточный режим с детерминированным временем CP-SAT для регрессии.
`search_status`: `feasible` (эвристика), `optimal_in_pool` (оптимум MILP только в пуле шаблонов — не
глобальный), `limited` (остановка по времени/отмене), `proven_optimal` только по тривиальному сертификату
«покрыты все индивидуально допустимые детали», `infeasible` — только если план не прошел валидацию.
Лексикографический порядок: выполненные закрепления → ≥5 свободных исходных кусков → площадь →
полностью покрытые заказы → стабильность действующих размещений → возраст использованных кусков.
Evidence плана включает `unconstrained_best_area_mm2` и `five_free_area_loss_mm2`.

## Интеграция для Pro

**Импорт.** После подтверждения импорта: `CuttingService(session).register_dataset(dataset_id, mode,
snapshot, parent_dataset_id=?, source_hash=?)`, где `snapshot` строится
`source_io.rows_to_snapshot(dataset_id, materials_rows, stock_rows, orders_rows)` (возвращает и построчные
ошибки `RowError(file,row,field,value,code,message_ru)`). `mode`: `source`/`contest` неизменяемы,
`workspace` изменяем. Рабочая копия: `create_working_copy(source_id, new_id)`.

**Jobs.** `POST /cutting/solve` берет `app.state.job_submitter.submit("cutting.solve", dataset_id,
payload)` → `Job` (202). Без submitter — честный 503 `JOB_PLATFORM_UNAVAILABLE`. Worker:
`CuttingEngine().solve(SolveInput.model_validate(payload), job_context)`; `job_context` реализует
`cancelled()`, `progress(stage, completed, total)`, `incumbent(CutPlan)` (публикуются только
валидированные планы; при отмене возвращается последний валидный). Coordinator в короткой write-транзакции:
`CuttingService(session).store_solver_plan(dataset_id, plan, base_plan_id=payload["base_plan_id"])` —
создает новую ревизию `validated`, ничего не подтверждает. Snapshot для job можно получить и через
`POST /cutting/solve-input`. Лимит потоков — `SolverConfig.workers` (по умолчанию в CLI `max(1, CPU−1)`).

**UoW и идемпотентность.** Сервис никогда не делает commit. До UoW Pro используется
`uow.write_transaction` (берет write lock SQLite первым оператором) и временная таблица `cut_idempotency`
(scope dataset+operation+key, hash тела, сохраненный результат; другой body → 409
`IDEMPOTENCY_KEY_REUSED`). При замене на платформенный сервис семантика та же.

**Миграции.** `migrations/0001_cutting.sql` (генерируется `render_ddl()`, тест держит синхронность):
таблицы `cut_datasets, cut_materials, cut_remnants, cut_parts, cut_plans, cut_placements,
cut_reservations, cut_audit_events, cut_idempotency`; частичные уникальные индексы
`uq_cut_plan_active (dataset_id) WHERE status='committed'` и
`uq_cut_reservation_active (remnant_row_id) WHERE status='active'`; CHECK на размеры, статусы, rot, lock.

**События для stale.** `GET /cutting/events?dataset_id&after_seq&object_id` и
`CuttingService.events(...)`: `remnant.added/updated/measured/withdrawn/restored/reserved/released/consumed/
children_recorded`, `plan.solver/edit/import/committed`, с before/after версиями и `seq`. Карточки и
напоминания перечитывают `GET /remnants/{id}` (status, version) при создании/открытии/подтверждении.

**Закрепления (C2-F1).** Исходные закрепления задачи (`SolveInput.locks`) сохраняются с ревизией
(`CutPlan.requested_locks`, колонка `cut_plans.locks_json`) и проверяются при store/validate/commit/export.
Нарушение любого из них делает ревизию `invalid` (альтернативная раскладка видна, но не подтверждается).
Снять закрепление можно только явной правкой `unlock`, которая создает новую ревизию.

**Экспорт (C2-F2), семантика live.** `GET /plans/{id}/export` → `SolutionExport`: точные строки в порядке
входа, header, результат валидатора, а также метрики и `free_original_remnant_ids`, вычисленные в одном
чтении текущего склада (`as_of`, `inventory_version`). Исторический список ревизии подписан отдельно:
`plan_free_original_remnant_ids`, `plan_inventory_version`, `inventory_changed_since_plan`,
`no_longer_free_remnant_ids`. Флаг `minimum_free_remnants_met` показывает, сохранился ли минимум свободных
кусков. Недопустимый план → 409. Pro сериализует CSV и повторно запускает неизмененный `validate.py`.
Перед созданием и подтверждением карточки — `GET /plans/{id}/free-remnants` (живой список с версиями кусков).

## Интеграция для C1 (UI)

- Схема: `GET /plans/{id}/layout` → по каждому куску `length_mm, width_mm, trim_mm (0 для калёного),
  gap_mm, tempered, tempered_tolerance_mm, defect, location_raw, rack, cell`, детали `x_mm, y_mm, w_mm,
  h_mm, rot, lock_kind, premium`. Начало координат — левый верхний угол; x вдоль длины. Табличная
  альтернатива строится из тех же полей. Для калёного не рисовать линии реза.
- Редактор: `POST /plans/{id}/draft` (`move/unplace/lock/unlock`) → новая ревизия и `validation.issues`
  с координатами; `invalid` остается редактируемой; `POST /plans/{id}/validate`; `POST /plans/compare`;
  `POST /plans/{id}/commit` с `expected_remnant_versions` и `Idempotency-Key`.
- Склад: `GET /datasets/{d}/remnants` (фильтры, сортировка, limit≤200), `POST /remnants`,
  `PATCH /remnants/{id}`, `PATCH /remnants/{id}/measurement` (ответ — ImpactReport),
  `POST /remnants/{id}/withdraw|restore|reserve|consume|release|children`, `POST /reservations/{id}/release`,
  `POST /cutting/impact`, `POST /cutting/candidates`.
- Демо 450/451 (ТЗ 40) не зашито: после подтверждения финального плана пример выбирается запросом
  `POST /cutting/candidates` в режиме `free_whole_remnants`; R006 не гарантируется.

## Интеграция для C3 (AI tools)

`find_remnants` → `CuttingPortAdapter(session_factory).find_candidates(FindRequest)` (только чтение,
`inventory_version` для повторной проверки). Подтверждение предложения резервирует целый кусок через
`POST /remnants/{id}/reserve` с `expected_version` (устаревшая версия → 409) и `owner_context="quote:<id>@<rev>"`.

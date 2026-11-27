# Статус CLAUDE_2_MYRZABEK

- Ветка: codex/claude-2-myrzabek-cutting
- Foundation commit: 16d63c6
- Последний проверенный commit: см. «Итоговый handoff» (обновляется последним коммитом ветки)
- Последнее обновление: 2026-11-27
- Общий статус: **READY FOR INTEGRATION** для модуля cutting/inventory. Полная продуктовая приемка не выполнена: требует Pro (jobs, импорт, UoW, экспорт), C1 (UI, E2E) и интеграционной сессии.
- Миссия: ../agents/CLAUDE_2_MYRZABEK.md · Технический договор модуля: ../../backend/glassflow/modules/cutting/README.md

## План и результат

| Пункт миссии | Статус | Реализованное поведение | Evidence | Что осталось |
|---|---|---|---|---|
| C2-01 Модели, контракты, подключение | done | DTO в `contracts/cutting.py` (аддитивно к foundation), домен `domain.py`, таблицы `cut_*`, `CuttingService`, `CuttingEngine` = `CuttingPort`, router на foundation-префиксе | `tests/cutting/test_contracts.py` | Pro: регистрация `0001_cutting.sql` в Alembic, замена `uow.py`/`cut_idempotency` платформенными |
| C2-02 Строгий валидатор | done | Независимый `geometry.validate_plan`, 21 стабильный код, координаты в ошибках, строгий парсер CSV | `test_geometry.py` (T08–T12), `test_random_validator.py` (T13, 600 примеров против неизмененного validate.py) | — |
| C2-03 Первый план и спецслучаи | done | Граф допустимости с причинами; точный max-weight matching калёного (Hungarian); 24 порядка Guillotine/MaxRects; incumbent публикуется только после валидации | `test_solver.py`: open pack quick 55,808% за ~1,9 с, официальный validate.py без ошибок | Замер на эталонном ноутбуке (T62) |
| C2-04 Усиленный оптимизатор | done | Пул конкретных раскладок, SciPy milp/HiGHS (≤1 шаблон/кусок, ≤1 использование детали, ≥5 свободных исходных кусков), column generation (LP-дуалы → эвристики + точный CP-SAT pricing), CP-SAT LNS с NoOverlap2D, лексикографическая фаза, профили, seed, fixed_work, ограничение пула, отмена | `test_solver.py` (T14, T16, T17, детерминизм) | — |
| C2-05 Качество | done (открытый набор) | Расширенный профиль продукта ≥ ориентира без чтения research CSV | `tests/cutting/evidence/open_extended_evidence.json` + `open_extended_solution.csv` (см. «Проверки») | Повтор на закрытом наборе — интегратор |
| C2-06 Склад, планы, редактор | done | Список/фильтры/пагинация, добавление, замер с ImpactReport, исключение/восстановление, место (стеллаж/ячейка), явный defect, неизвестный возраст = null, immutable snapshot → 409; draft edit (move/unplace/lock/unlock) → новая ревизия; validate/compare/impact; locks в пересчете; режим `keep_committed`; быстрый подбор с совместной вместимостью количества | `test_inventory_api.py`, `test_scenarios.py` | UI (C1) |
| C2-07 Атомарные резервы | done | available→reserved→consumed, available→withdrawn, reserved→available до расхода; один резерв на целый кусок; commit: ревизия, версии, доступность, полная валидность, CAS-UPDATE, partial unique index, audit, idempotency; резерв целого куска под предложение (`/remnants/{id}/reserve`); дочерние куски только после расхода, `original=false` | T18 (5 повторов: всегда 200+409), T19, T20, T23-часть | Платформенный UoW/idempotency Pro |
| C2-08 Метрики и интеграционные данные | done | covered mm², coverage, точный процент строкой, полностью покрытые заказы, used/free исходные куски, причины NEW, оценка материала Decimal по materials (не прибыль), формула балла, `SolutionExport`, `PlanLayout`, события | `metrics.py`, `test_layout_and_export_contracts` | Pro: сериализация CSV + повторный validate.py; C1: SVG |
| C2-09 Проверка и handoff | done для модуля | 58 тестов cutting (57 выполняются + 1 длинный T15 по флагу), синтетический набор с новыми ID/перестановкой, пустые/невозможные случаи, сохранение активного плана при failed job | этот файл | Сквозные T23/T48/T50/T55/T62 — после слияния |

## Проверки

Среда: Windows 11, Python 3.12 (uv), 8 логических CPU, Node v26.1.0 (ТЗ требует 24 — отличие среды, на типы не влияет), pnpm 11.25.0 через npx.

| ID / команда | Вход / среда | Фактический результат | Статус | Evidence |
|---|---|---|---|---|
| `uv run ruff check backend tests scripts` | ветка | All checks passed | PASS | — |
| `uv run pytest` | ветка | все тесты проходят (cutting + foundation), 1 skipped = длинный T15 | PASS | — |
| `uv run python scripts/check_foundation.py` | ветка | 14 immutable inputs, 66/67 матрица, PDF | PASS | — |
| `pnpm typecheck`, `pnpm test` | после регенерации схемы | tsc OK, 2 web-теста | PASS | — |
| T08 край 5 мм / 4 мм | синтетика | 5 принят, 4 и правый/нижний +1 отклонены, официальный check() согласен | PASS | test_geometry |
| T09 зазор 3/2 мм | синтетика | 3 принят, 2 → GAP_VIOLATION обеим деталям | PASS | test_geometry |
| T10 rot, материал, premium/defect | синтетика | rot меняет оси; MATERIAL_MISMATCH, PREMIUM_ON_DEFECT | PASS | test_geometry |
| T11 калёное ±2/3, две детали | синтетика | ±2 без обрези принят; 3 и вторая деталь отклонены | PASS | test_geometry |
| T12 дубли/пропуски | синтетика | DUPLICATE_PART/MISSING_PART блокируют; официальный скрипт пропуск не ловит — наш ловит | PASS | test_geometry, export → 409 |
| T13 случайные задачи | Hypothesis 600 планов + 60 решений solver | валидность совпадает с validate.py, решения solver всегда чисты | PASS | test_random_validator |
| T14 лимит и отмена | open pack | cancelled/time_limit → `limited`, последний валидный incumbent, нет ложного OPTIMAL/INFEASIBLE | PASS | test_solver |
| T15 расширенный профиль | open pack, extended 600 с, 7 потоков, seed 42 | см. блок «Качество раскроя» | PASS (открытый набор) | evidence JSON/CSV |
| T16 locks и исключение | синтетика + HTTP | закрепления соблюдены, конфликт явный, impact/compare корректны, активный план не меняется до commit | PASS | test_solver, test_inventory_api |
| T17 (support) пять свободных | синтетика | ограничение соблюдено, точная потеря площади в evidence | PASS (часть C2) | test_solver; карточки — Pro |
| T18 конкурентный резерв | реальная SQLite, 2 потока, барьер | ровно 200+409, одна активная резервация на кусок, один committed план; 5/5 повторов | PASS | test_inventory_api |
| T19 idempotency | реальная SQLite | тот же ключ+тело → тот же ответ без новых audit; другое тело → 409 | PASS | test_inventory_api |
| T20 добавить→рестарт→резерв→расход | новый app на той же БД | место сохранено, после расхода кусок исключен из подбора, история событий | PASS | test_inventory_api |
| T22 недопустимый перенос (сервер) | HTTP | OUT_OF_BOUNDS с координатами, commit/экспорт отклонены, черновик исправлен новой ревизией | PASS (серверная часть) | test_inventory_api; UI-часть — C1 |
| T23 (support) версия изменилась во время ответа | open pack HTTP | резерв со старой версией → 409, после перечитывания успешен | PASS (часть C2) | test_scenarios |
| T62 (support) подбор одной детали | 200 остатков, 200 запросов | median ≈11 мс, p95 ≈16 мс (ноутбук разработчика) | PASS (цель ≤1 с) | evidence/candidate_search_timing.json |
| T62 (support) первый план | open pack quick | ≈1,9 с | PASS (цель ≤5 с, не эталонная машина) | test_solver |
| T01, T03, T04, T05, T26, T27, T36, T44, T46, T48, T50, T51, T53, T55, T57–T61, T67 | — | моя часть реализована (изоляция dataset_id, строгий импорт строк, события stale, экспорт строк, offline-ядро без сети) | NOT RUN как сквозные | требуют Pro/C1/интегратора |

## Качество раскроя (C2-05)

Открытый набор, продуктовый движок (не research-скрипты, research CSV не читаются):

| Показатель | Финальный evidence-прогон (код 1ac9816) |
|---|---|
| Профиль | extended, seed 42, 7 потоков, лимит 600 с, minimum_free_remnants=5 |
| Время / остановка | 145,4 с; `optimal_in_pool` / `completed` (терпение 12 раундов без улучшения) |
| Покрытие | **59,0488271%** (110 934 500 мм² из 187 869 100 мм²) — не хуже 58,9523237% |
| Детали / куски | 198 из 298 деталей; 146 использованных кусков; 54 полностью свободных исходных |
| Полностью покрытые заказы | 43 из 110 |
| Оценка материала по прайсу | 1 019 072,95 ₸ (не прибыль) |
| Формула балла (открытый набор) | 12,065 из 20 (не официальный результат жюри) |
| Внутренний валидатор | invalid=0, missing=0 |
| Неизмененный validate.py (`python -X utf8`) | `RESULT coverage=0.590488 invalid=0 money=1019073`, exit 0 |
| Причины NEW | LIMITED_SEARCH 73, TEMPERED_SIZE_MISMATCH 22, SIZE_TOO_LARGE 4, PREMIUM_ON_DEFECT 1 |
| Хеши | stock 4e24ce0a…; orders 9ac22256…; materials 1391e1fa…; validate.py 0d276077…; solution ddfc9aba… |

`git_commit` в evidence помечен `+dirty` только из-за неотслеживаемого тогда `modules/cutting/README.md` (документ); код совпадает с 1ac9816.

Другие прогоны того же профиля (многопоточный wall-clock поиск не обещает идентичный план, ТЗ 12): 59,0794335% (164 с), 59,0831595% (600 с, лимит). Все ≥ ориентира, все с официальным invalid=0.

Ориентир ТЗ: 58,9523237%. Сравнение с условием пяти свободных кусков: лучший найденный план без этого условия имеет ту же площадь (`five_free_area_loss_mm2 = 0` в evidence). `search_status=limited` означает остановку по бюджету 600 с; это не глобальный оптимум и не доказанная невозможность. Верхняя граница не публикуется продуктом (research-граница 61,4086% относится только к исследовательской модели открытого набора).

Воспроизвести:

```
uv run python -m glassflow.modules.cutting.cli solve --pack inputs/PACK_for_teams/1_ostatki --profile extended --time 600 --out .runtime/cutting/solution.csv --evidence .runtime/cutting/evidence.json
```

## Контракты и интеграция

Подробный договор: `backend/glassflow/modules/cutting/README.md`. Кратко:

- Маршруты (все `/api/v1`): `GET /remnants` (foundation, list + `X-Total-Count`), `GET /datasets/{d}/remnants` (RemnantPage), `GET/PATCH /remnants/{id}`, `POST /remnants`, `POST /datasets/{d}/remnants`, `PATCH /remnants/{id}/measurement`, `POST /remnants/{id}/withdraw|restore|reserve|consume|release|children`, `POST /reservations/{id}/release`, `GET /cutting/events`, `POST /cutting/candidates|solve|solve-input|impact`, `GET /plans`, `GET /plans/active`, `GET /plans/{id}`, `GET /plans/{id}/layout|export`, `POST /plans/{id}/draft|validate|commit`, `POST /plans/compare`.
- DTO: все новые поля аддитивны со значениями по умолчанию; foundation-поля сохранены. `packages/contracts/openapi.json` и `schema.d.ts` регенерированы штатными командами.
- Fixture-only: только `InlineJobSubmitter` в `tests/cutting/conftest.py` (тестовая замена очереди). В релизе без платформенного submitter `/cutting/solve` честно отвечает 503.
- Миграции: `backend/glassflow/modules/cutting/migrations/0001_cutting.sql` (9 таблиц, 2 частичных уникальных индекса). Shared Alembic revision не создавался.

### Запросы к Pro (не применены, предложение)

1. **Job submitter**: предоставить в `app.state.job_submitter` объект `submit(kind, dataset_id, payload) -> Job`; worker вызывает `CuttingEngine().solve(SolveInput, JobContext)`, coordinator — `CuttingService(session).store_solver_plan(dataset_id, plan, base_plan_id=payload.get("base_plan_id"))`. Потребители: UI, AI compare_scenario, run coordinator.
2. **UoW**: заменить `modules/cutting/uow.write_transaction` платформенной write-транзакцией, которая берет write lock до чтения версий (аналог BEGIN IMMEDIATE). Сервис не коммитит.
3. **Idempotency**: при появлении платформенного сервиса заменить `CuttingService.idempotent` и таблицу `cut_idempotency` (scope dataset+operation+key, hash тела, replay результата).
4. **Импорт**: в commit импорта вызывать `rows_to_snapshot` + `register_dataset`; построчные `RowError` показать в предпросмотре.
5. **Единый формат ошибок**: router уже возвращает `ApiError`; при глобальном обработчике 422 Pro может убрать локальную обертку.
6. **Run/экспорт**: брать `GET /plans/{id}/export` (или `CuttingService.export`) и `free_original_remnant_ids`; при недопустимом плане экспорт блокируется 409.

## Артефакты и источники

| Путь | Происхождение |
|---|---|
| `tests/cutting/evidence/open_extended_solution.csv` | продуктовый расширенный прогон, проверен неизмененным validate.py |
| `tests/cutting/evidence/open_extended_evidence.json` | config, seed, потоки, время, хеши входов/валидатора/решения, git commit, метрики, stdout/stderr/exit validate.py, траектория incumbents |
| `tests/cutting/evidence/candidate_search_timing.json` | замер подбора (перезаписывается тестом) |

Атрибуция: семейства Guillotine/MaxRects и идея «пул + set-packing MIP» перенесены из `analysis/cutting/research.py`/`patterns.py` (переписаны, не импортируются); MaxRects/Guillotine — J. Jylänki, «A Thousand Ways to Pack the Bin» (2010). Библиотеки: SciPy (HiGHS), OR-Tools CP-SAT, NumPy, SQLAlchemy, FastAPI, Pydantic, Hypothesis.

## Внешние блокеры

- Платформенные jobs/UoW/импорт/экспорт (Pro) — не блокируют модуль; HTTP-solve без submitter отвечает 503. Проверены через тестовый submitter.
- UI (C1) — T22 визуальная часть, T57.
- Эталонный ноутбук и frozen worker (T55, T62 полностью) — интеграция/Pro.
- Node 24 в среде отсутствует (установлен 26); проверки typecheck/test прошли с предупреждением engines.

## Следующий шаг

Интеграционная сессия: слить ветку, подключить job submitter и импорт, прогнать `uv run pytest tests/cutting`, затем сквозные сценарии из «Итогового handoff».

## Итоговый handoff

Коммиты ветки поверх foundation 16d63c6: a25ba0c (валидатор, solver, сервис), 4a2c8ee (HTTP, SQLite-интеграция, контракты), 1ac9816 (резерв под предложение, миграции, сценарии), затем коммит этого статуса и README модуля.

**Готово и проверено в ветке:** C2-01…C2-09 в объеме модуля; T08–T16, T18–T20, T22 (сервер) — PASS по автоматическим тестам; T15 — PASS на открытом наборе по evidence.

**Ожидает интеграционной проверки:** T17/T48 (карточки Pro по `free_original_remnant_ids`), T23 (AI C3 + резерв), T50/T51 (новый набор через импорт и экспорт Pro, неизмененные скрипты на Windows), T55 (frozen worker вызывает `CuttingEngine`), T62 (эталонная машина), T22/T57 (UI C1).

**Порядок проверки после объединения:**
1. `uv run pytest tests/cutting -q` и `GLASSFLOW_RUN_EXTENDED=1 uv run pytest tests/cutting/test_scenarios.py -k t15` (≈10 мин).
2. Импорт открытого пакета → `register_dataset` → `POST /cutting/solve` (через реальную очередь) → `GET /jobs/{id}` → план `validated`.
3. `POST /plans/{id}/commit` с версиями и Idempotency-Key; повтор; конкурентный commit из двух вкладок → 200/409.
4. `GET /plans/{id}/export` → Pro пишет solution.csv → `python -X utf8 validate.py ...` → invalid=0.
5. Карточки только из `free_original_remnant_ids`; затем изменить план → карточки stale по `/cutting/events`.
6. Демо ТЗ 40: `POST /cutting/candidates` clear-6 450×370 и 451×370 в `free_whole_remnants` на финальном плане — пример выбирать по факту.

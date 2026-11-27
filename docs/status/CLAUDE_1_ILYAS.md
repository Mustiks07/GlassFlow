# Статус CLAUDE_1_ILYAS

- Ветка: `codex/claude-1-ilyas-ui`
- Foundation commit: `16d63c6`
- Последний проверенный commit: см. `git log` ветки (checkpoint записан после `987cb6e`)
- Последнее обновление: 27.11.2026, Asia/Qyzylorda
- Общий статус: **IN PROGRESS** — UI C1-01…C1-06 реализован и проверен на fixture и частично на реальном backend; C1-07 (покупатели) и C1-09 (питч) в работе. Это не COMPLETE VERIFIED PRODUCT.
- Миссия: [../agents/CLAUDE_1_ILYAS.md](../agents/CLAUDE_1_ILYAS.md)

## План и результат

| Пункт | Статус | Реализовано | Evidence | Осталось |
|---|---|---|---|---|
| C1-01 клиент API и дизайн-система | READY FOR INTEGRATION | Единый `ApiClient`: dataset_id, токен сессии в памяти (`X-GlassFlow-Session`), `Idempotency-Key` на действие, `X-Request-ID`, correlation_id в ошибках, русские field errors, отдельные состояния 409/422/429/501/503/offline/timeout, «маршрут не опубликован» для framework 404/405. TanStack Query + Zustand. Токены CSS, таблицы, диалоги Radix (Escape, возврат фокуса), статусы «значок+текст», loading/empty/error/stale/offline-AI на каждом экране. Fixture-транспорт только по `VITE_GLASSFLOW_TRANSPORT=fixture`, без fallback | vitest 20/20; `check:bundle` PASS (fixture-сборка — ожидаемый FAIL как положительный контроль) | Перегенерация типов после интеграции |
| C1-02 навигация, импорт, настройки | READY FOR INTEGRATION | 7 разделов (hash-маршруты переживают refresh), выбор набора и режим source/workspace/contest в шапке, рабочая копия с подтверждением; импорт файлы→предпросмотр→построчные ошибки (файл/строка/поле/исходное значение/причина)→явный commit, повтор тех же байтов → существующий снимок; AI-профиль (free_only по умолчанию, paid только с бюджетом и явной отметкой, masked key не хранится в браузере, проверка соединения); backup/restore/shutdown с подтверждением | real E2E T01/T02/working copy PASS | Список бэкапов и журнал: маршрутов у Pro нет — UI честно показывает «не подключено» |
| C1-03 рабочее место | READY FOR INTEGRATION; real T28 FAIL (интеграция C3↔Pro) | Свободный запрос + история, рабочая карточка C3 (подтвержденные параметры/предположения/недостающее/факты), перенос в форму только по кнопке; форма с мм/см/м и показом пересчета, неоднозначность → уточнение; расчет только сервером; ревизии через `/quotes/{id}/revise` (stale старого итога, diff ревизий); unmapped/ambiguous/proposed отличается от «нет на складе» и NEW; кандидат с местом и SVG; подтверждение C3 `{expected_revision, confirmed_by}`; резерв — отдельное явное действие с expected_version + idempotency, 409 → обновление склада; заказчик ≠ адресат CRM; QA диалога OK/ERROR/NEEDS_REVIEW | fixture route1/route2/T23/T27/T28/T36/T43 PASS | Атомарное «подтвердить+зарезервировать» — запрос к C2/C3 ниже |
| C1-04 раскрой | READY FOR INTEGRATION; real BLOCKED (C2 не опубликован) | Таблицы остатков/деталей с фильтрами и местом, SVG (масштаб, zoom, край 5 мм, зазор 3 мм, легенда, масштабная линейка), drag, стрелки/Shift, R-поворот, точные x/y, lock placement/assignment, смена куска/NEW, исключение куска, замер, списание, добавление; черновик хранится локально и не меняет активный план; save→validate→commit с expected_remnant_versions; job panel (реальный этап, n из m, бюджет, requested vs stopped, last valid); сравнение версий; табличная альтернатива; калёное без линий реза | fixture T22, клавиатура, калёное, job/compare, причины NEW PASS | Реальные маршруты C2 |
| C1-05 CRM, M1–M5, карточки | READY FOR INTEGRATION | 25 строк и очередь по client_id (порядок сервера), происхождение признаков и фактическая метка отдельно; редактор напоминаний (адресат, исходные заявки, 3 типа предмета, срок Asia/Qyzylorda, ответственный, активные дубли), confirm/cancel/done, stale блокирует подтверждение; M1–M5 семь метрик + средняя сумма всех заявок отдельно, фильтры, знаменатели, полнота, drill-down строк, NULL ≠ 0; карточки: реестр по версии, импорт buyers CSV+evidence, коэффициент 0,30–0,70 (PATCH), recheck, stale блокирует экспорт | real T40/T42/T45/T43 PASS; fixture T44/T48/T49 PASS | — |
| C1-06 конкурсный экран | READY FOR INTEGRATION | Входы с хешами и строками, модули, AI-профиль, run_id, статусы модулей, manifest, частичный пакет, скачивание файлов одного run, без официальных баллов без KEY | real route 4 (CRM) PASS с проверкой скачанного picks.csv; fixture route4/T53 PASS | Полный run после C2/C3 |
| C1-07 50 покупателей | IN PROGRESS | — | — | Исследование и `data/buyers/` |
| C1-08 Browser/E2E | DONE для доступного объема | `e2e:fixture` (59 проверок, 3 профиля) и `e2e:real` (10 сценариев) — отдельные команды и результаты | см. Проверки | Повтор на интегрированной ветке |
| C1-09 питч | NOT STARTED | — | — | Слайды, PDF, сценарий, план замеров |

## Проверки (фактические)

| Команда / среда | Результат | Статус |
|---|---|---|
| `pnpm --filter @glassflow/web test` | 20/20 | PASS |
| `pnpm typecheck`, `pnpm build` | без ошибок | PASS |
| `pnpm --filter @glassflow/web check:bundle` | dist без fixture и шаблонов ключей | PASS |
| `pnpm --filter @glassflow/web e2e:fixture` (1366×768, 1920×1080, zoom 125 % ≈ 1093×614 @1.25) | 59 passed | PASS (fixture, не backend) |
| `pnpm --filter @glassflow/web e2e:real` против локальной тестовой сборки GPT Pro `6512eae` + Claude 3 `4616645` (не опубликована, только для проверки), свежая БД | 8 passed, 2 failed | T01, T02, рабочая копия, T40/T42 (25/15/80 %), T45, T43, AI check+backup, route 4 CRM — PASS; T28 — FAIL: C3 `/catalog` возвращает `DATASET_NOT_FOUND` для наборов Pro; R05 cutting — FAIL: C2 маршруты 501 |
| Foundation: `uv run pytest`, ruff, check_foundation (до изменений) | 7 passed, PASS | PASS |

Найденные E2E и исправленные дефекты UI: потеря адресата после создания напоминания; skip-link не первый Tab; диалоги не возвращали фокус; нечитаемые подписи SVG на превью; форма клиента уезжала из вида; статус модулей прогона при Job без kind; ложная «остановка подтверждена» на завершенном задании.

## Контракты: что использует UI и запросы владельцам

Типы — `apps/web/src/api/types.ts` (расширения уже реализованных полей Pro/C3 и `Proposed*`), операции — `apps/web/src/api/endpoints.ts`.

Запросы (точные, обратно совместимые):
1. **C2**: `GET /cutting/parts?dataset_id` → `Part[]`; `GET /cutting/materials?dataset_id` → `Material[]`; `GET /plans?dataset_id` → `CutPlan[]`; `POST /plans/{id}/draft` `{dataset_id, base_revision, placements, excluded_remnant_ids}` → `CutPlan` (новая ревизия draft/invalid); `POST /plans/{id}/validate?dataset_id&revision`; `POST /plans/compare` `{dataset_id, base_plan_id, candidate_plan_id}` → Δплощади/Δоценки/Δзаказов, новые NEW, затронутые quote/card; `PATCH /remnants/{id}/measurement` `{dataset_id, expected_version, previous_dimensions, dimensions, reason}`; `POST /remnants/{id}/consume|release` `{dataset_id, expected_version, reservation_id, reason}`; **`POST /remnants/{id}/reserve`** `{dataset_id, expected_version, owner_context:{kind:'quote', quote_id, quote_revision}}` + Idempotency-Key. Поля `CutPlan.new_reasons{part_id: reason}`, `Candidate.length_mm/width_mm`, `Job.elapsed_seconds/budget_seconds`.
2. **C3+C2 (атомарность, спецификация §9)**: `QuoteConfirmRequest` + необязательные `remnant_id`, `expected_remnant_version` — подтверждение и резерв одной транзакцией. До этого UI делает два явных действия.
3. **C3↔Pro**: intelligence должен видеть наборы, импортированные Pro (сейчас `DATASET_NOT_FOUND`); `Dataset.kb_version` (UI пока использует `sha256:<source_hashes.kb>`).
4. **Pro**: `Job.kind`; `GET /system/backups`, `GET /system/journal`; `AISettings.allowed_models`.

Fixture-only места: весь `apps/web/src/api/fixtures/**` (только тесты и `dev:fixture`, фиолетовый баннер).

## Следующий точный шаг

C1-07: найти и проверить 50 публичных организаций (≥30 Астана, ≥5 категорий), записать `data/buyers/buyers_candidate.csv` и `evidence.json`. Затем C1-09 и итоговый handoff.

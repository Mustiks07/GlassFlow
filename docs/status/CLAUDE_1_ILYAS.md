# Статус CLAUDE_1_ILYAS

- Ветка: `codex/claude-1-ilyas-ui` (от foundation `16d63c6`)
- Последний проверенный commit: `866393b` + этот status
- Обновлено: 27.11.2026, Asia/Qyzylorda
- Общий статус: **READY FOR INTEGRATION.** Весь backlog C1-01…C1-09 выполнен в объеме, проверяемом без объединенной сборки. Полная приемка продукта (общий маршрут на интегрированной ветке, чистая Windows, репетиция питча, финальные числа) — **не выполнена** и не заявляется.
- Миссия: [../agents/CLAUDE_1_ILYAS.md](../agents/CLAUDE_1_ILYAS.md)

## Итог по пунктам

| Пункт | Статус | Что сделано | Evidence | Что осталось после интеграции |
|---|---|---|---|---|
| C1-01 API-клиент, дизайн-система | READY FOR INTEGRATION | Единый `ApiClient`: dataset_id, токен сессии только в памяти (`X-GlassFlow-Session`), `Idempotency-Key` на все confirm/commit/reserve/consume/export (ключ живет все действие, повтор после ошибки — тот же ключ), `X-Request-ID`, correlation_id в ошибках, русские field errors, отдельные состояния 409/422/429(Retry-After)/501/503/offline/timeout, «операция не опубликована» для framework 404/405. TanStack Query + Zustand. Токены CSS, плотные таблицы, Radix-диалоги (Escape, возврат фокуса), статусы «значок+текст», loading/empty/error/stale/offline-AI. Fixture только по `VITE_GLASSFLOW_TRANSPORT=fixture`, без fallback | vitest 20/20; `check:bundle` PASS (fixture-сборка — ожидаемый FAIL, положительный контроль) | Перегенерировать `schema.d.ts` из объединенных DTO и удалить временные расширения в `apps/web/src/api/types.ts` |
| C1-02 навигация, импорт, настройки | READY FOR INTEGRATION | 7 разделов (hash-маршруты переживают refresh), набор и режим source/workspace/contest в шапке, рабочая копия с подтверждением; импорт файлы→предпросмотр→построчные ошибки (файл/строка/поле/исходное значение/причина)→явный commit; повтор тех же байтов открывает существующий снимок; AI-профиль: free_only по умолчанию, paid только с бюджетом и явной отметкой, ключ не хранится в браузере; backup/restore/shutdown | real E2E T01, T02, рабочая копия, AI check + backup — PASS | Pro: `GET /system/backups`, `GET /system/journal` (UI показывает «не подключено») |
| C1-03 рабочее место | READY FOR INTEGRATION; real T28 FAIL (стык C3↔Pro) | Свободный запрос + история; рабочая карточка C3 (подтвержденные параметры, предположения, недостающее, факты, путь ответа); перенос в форму только по кнопке; мм/см/м с показом пересчета, неоднозначность → уточнение; расчет только сервером (`inventory_mode=free_whole_remnants`); ревизии `/quotes/{id}/revise` с stale старого итога и diff; unmapped/proposed/ambiguous ≠ «нет на складе» ≠ NEW; кандидат со стеллажом/ячейкой и SVG; подтверждение C3 `{expected_revision, confirmed_by}`; резерв — отдельное явное действие C2 `/remnants/{id}/reserve` с expected_version, 409 → обновление склада; заказчик ≠ адресат CRM; QA диалога OK/ERROR/NEEDS_REVIEW с эталоном и упоминаниями цен | fixture route1/route2/T23/T27/T28/T36/T43 PASS | После стыка C3↔Pro повторить real T28 |
| C1-04 раскрой | READY FOR INTEGRATION; real FAIL (стык C2↔Pro) | Контракт C2 `5897472`: остатки (место, rack/cell, статус), детали и материалы из `solve-input`, `PlanSummary`, SVG (масштаб, zoom, край 5 мм, зазор 3 мм, легенда, линейка), drag, стрелки/Shift, R, точные x/y, lock placement/assignment, смена куска/NEW; черновик → `draft` edits → новая ревизия с валидацией, дальнейшая правка на ней, активный план не меняется; commit с expected_remnant_versions; исключение куска → `/cutting/impact` + solve с `excluded_remnant_ids`; `keep_committed`; замер, withdraw/consume; job panel (этап, n из m, бюджет, requested vs stopped, last valid); compare (`PlanComparison`); причины NEW по кодам C2; табличная альтернатива; калёное без линий реза | fixture T22, клавиатура, калёное, job/compare, причины NEW PASS | Повторить real R05/T22 на интегрированной ветке |
| C1-05 CRM, M1–M5, карточки | READY FOR INTEGRATION | 25 строк и очередь по client_id (порядок сервера), признаки и фактическая метка отдельно; напоминания (адресат, исходные заявки, 3 типа предмета, срок Asia/Qyzylorda, ответственный, активные дубли), confirm/cancel/done, stale блокирует подтверждение; M1–M5 семь метрик + средняя сумма всех заявок отдельно, подписи по уточнению от 27.11, фильтры, знаменатели, полнота, drill-down, NULL ≠ 0; карточки: реестр по версии, импорт CSV+evidence, живая перепроверка свободных кусков C2, коэффициент 0,30–0,70 (PATCH), recheck, stale блокирует экспорт | real T40/T42 (25/15/80 %), T45, T43 PASS; fixture T44/T48/T49 PASS | — |
| C1-06 конкурсный экран | READY FOR INTEGRATION | Входы с хешами/строками, модули, AI-профиль, run_id, статусы модулей (из `missing_modules`, т.к. Job без kind), manifest, частичный пакет, скачивание файлов одного run, без официальных баллов без KEY | real route 4 (CRM) PASS на Pro+C3, скачанный picks.csv: заголовок, 25 уникальных ID, без BOM; fixture route4/T53 PASS | Полный run после стыков C2/C3 |
| C1-07 покупатели | DONE (кандидат), окончательный CSV выпускает Pro | 50 уникальных, 49 Астана, 9 категорий; evidence с HTTP-статусом, заголовком, подтверждением города/профиля, фрагментом, датой, reviewer и правилом дедупликации; `verify_buyers.py` воспроизводит | `python3 data/buyers/verify_buyers.py` → 0 проваленных | Pro: импорт и `buyers_top50.csv`; второй проверяющий — 10 случайных строк |
| C1-08 Browser/E2E | DONE в доступном объеме | `e2e:fixture` (59 проверок, 1366×768, 1920×1080, zoom 125 %) и `e2e:real` (10 сценариев) — отдельные команды и отчеты; скриншоты в `tests/e2e/evidence/{fixture,real}` | см. Проверки | Повтор `e2e:real` на интегрированной ветке со свежей БД |
| C1-09 питч | READY FOR INTEGRATION, не FINAL | 6 слайдов PPTX (генератор), PDF с встроенными шрифтами, сценарий 3:00 (live 25+5 с), ответы на вопросы, план замеров 10 задач; только реальные кадры; непроверенные числа — `[ФИНАЛЬНЫЙ RUN]` | `docs/presentation/*`, PDF открыт и просмотрен | Заполнить числа одного финального run, репетиция T60, замеры (люди) |

Дефекты, найденные моими E2E и исправленные в UI: потеря адресата после создания напоминания; skip-link не первый Tab; диалоги не возвращали фокус; нечитаемые подписи SVG на превью; форма клиента уезжала из вида; статус модулей прогона при Job без kind; ложная «остановка подтверждена» на завершенном задании; после сохранения черновика правки считались от старой ревизии.

## Проверки (фактические, 27.11.2026)

| Команда / среда | Результат | Статус |
|---|---|---|
| `uv run pytest`, `uv run ruff check backend tests scripts`, `uv run python scripts/check_foundation.py` | 7 passed; All checks passed; PASS 14/66/67 | PASS |
| `pnpm typecheck`, `pnpm build` | без ошибок | PASS |
| `pnpm test` (vitest) | 20/20 | PASS |
| `pnpm --filter @glassflow/web check:bundle` | dist без fixture и шаблонов ключей | PASS |
| `pnpm --filter @glassflow/web e2e:fixture` | 59 passed (3 профиля) | PASS — fixture, не backend |
| `pnpm --filter @glassflow/web e2e:real` на локальной тестовой сборке Pro `6512eae` + C3 `4616645` (не публиковалась), свежая БД | 8/10: T01, T02, рабочая копия, T40/T42, T45, T43, AI+backup, route 4 CRM — PASS; T28 FAIL (`/catalog` → `DATASET_NOT_FOUND` для наборов Pro); R05 FAIL (C2 тогда 501) | частично |
| то же на наивном слиянии Pro `e247927` + C3 `6cc73b9` + C2 `5897472` | C2 `/remnants`, `/plans` → `CONCURRENT_UPDATE` (503, retryable) — C2 не подключен к UoW/композиции Pro; C3 по-прежнему `DATASET_NOT_FOUND`; route 4 тоже упал | BLOCKED (интеграция) |

## Контракты: что использует UI и запросы владельцам

Операции — `apps/web/src/api/endpoints.ts`; типы — `apps/web/src/api/types.ts` (расширения реализованных полей Pro `e247927`, C3 `6cc73b9`, C2 `5897472`; ручных правок generated-файлов нет).

1. **Интегратор/Pro + C2**: зарегистрировать сервис C2 в композиции Pro (общая транзакция/сессия, import hooks), иначе `CONCURRENT_UPDATE`. Подключить C2 job handler `cutting.solve` к `job_submitter`.
2. **Интегратор/Pro + C3**: intelligence должен видеть наборы, импортированные Pro (сейчас `DATASET_NOT_FOUND`); `Dataset.kb_version` (UI пока берет `sha256:<source_hashes.kb>`).
3. **C3 + C2, атомарность ТЗ §9**: необязательные `remnant_id`, `expected_remnant_version` в `QuoteConfirmRequest`, чтобы подтверждение и резерв шли одной транзакцией. Сейчас UI выполняет два явных действия (C3 confirm, C2 reserve с `owner_context="quote:<id>:rev<n>"`).
4. **Pro**: `Job.kind` (UI сейчас выводит статус модуля из `missing_modules`); `GET /system/backups`, `GET /system/journal`; `AISettings.allowed_models`.
5. **Pro (U01 из плана v1.1)**: общий DTO двух форм «предложение клиенту / задание складу» — UI готов добавить вторую форму поверх существующих фактов после публикации DTO.

Fixture-only: весь `apps/web/src/api/fixtures/**` (тесты и `dev:fixture`, фиолетовый баннер; в production-сборку не попадает).

## Порядок проверки после объединения

1. Регенерировать контракты: `uv run python scripts/export_openapi.py`, `pnpm contracts:generate`; `pnpm typecheck`.
2. `pnpm test`, `pnpm build`, `pnpm --filter @glassflow/web check:bundle`.
3. Свежая БД, backend + `pnpm dev` (или собранный UI на :8000 с `GLASSFLOW_E2E_URL=http://127.0.0.1:8000`), затем `pnpm --filter @glassflow/web e2e:real`. Ожидаемо все 10 PASS после стыков п.1–2.
4. `pnpm --filter @glassflow/web e2e:fixture` — регрессия UI-состояний.
5. Перед защитой: `python3 data/buyers/verify_buyers.py`, заполнить `[ФИНАЛЬНЫЙ RUN]` в `docs/presentation/build_deck.py`, пересобрать PPTX/PDF, репетиция по `PITCH_SCRIPT.md`.

## Внешние блокеры

- Стыки композиции C2/C3 с платформой Pro (см. выше) — блокируют real T28/R05 и полный run; UI-часть готова и проверена fixture-тестами.
- Финальные числа раскроя/экономики/AI — только после одного финального run Pro.
- Репетиция питча (T60), замеры 10 задач, чистая Windows, Drive/дедлайны (T54, T63–T66) — требуют людей/оборудования; NOT RUN.

## Следующий шаг

Ветка готова к интеграции. После появления `codex/integration`: шаги «Порядок проверки» 1–5, затем обновить реальные кадры и числа в питче.

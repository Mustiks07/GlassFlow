# Статус CLAUDE_3_MUSTAFA

Рабочий checkpoint агента. Foundation не означает готовность продукта; статусы ниже различают «реализовано», «проверено», «ожидает интеграции» и «заблокировано».

- Ветка: `codex/claude-3-mustafa-ai` (опубликована в origin). В main не сливалась.
- Foundation commit: `16d63c6`. Проверенный ревьюером commit: `e83c211`.
- Последний проверенный код-коммит: см. раздел «Итоговый handoff» (этот статус — в том же или следующем коммите, см. `git log`).
- Последнее обновление: 28.11.2026 (ночь, Asia/Qyzylorda).
- Общий статус: **READY FOR INTEGRATION** для детерминированного ядра (каталог, расчеты, диалог, контроль диалогов, шлюз-engine) и исправлений независимой проверки F1–F4. Живые проверки выполнены с тестовыми бесплатными ключами владельца: онлайн-путь на 18 открытых вопросах — **PASS**, на расширенных 24 кейсах ×3 — **FAIL** (81,4% < 95%), повтор критических ×3 на выбранной модели после F4 — **BLOCKED** (дневная квота 500 запросов исчерпана). По умолчанию работает гибрид (детерминированный путь, модель только для нераспознанных запросов). Развертывание шлюза по HTTPS не выполнялось (нет хостинга). Полная приемка продукта не выполнялась (это задача интегратора).
- Миссия: [../agents/CLAUDE_3_MUSTAFA.md](../agents/CLAUDE_3_MUSTAFA.md). Подробности: [docs/ai/README.md](../ai/README.md), [EVALUATION.md](../ai/EVALUATION.md), [MODEL_SELECTION.md](../ai/MODEL_SELECTION.md), [ECONOMICS.md](../ai/ECONOMICS.md).

## Исправления независимой проверки (docs/reviews/CLAUDE_3_REVIEW_2026-11-27.md)

Каждое исправление воспроизведено до и после; эталоны не подбирались под поведение (ожидания взяты из ревью и пересчитаны вручную по KB).

| Находка | До (e83c211) | После | Commit | Тесты / evidence |
|---|---|---|---|---|
| F1 P1 неоднозначный товар | «Почём зеркало 4 мм?» + «Цена 99999 тг.» → ERROR, correct 9500, выбрано по рангу | NEEDS_REVIEW, correct=null, reason `ambiguous_product_correction_not_unique`, в объяснении перечислены трактовки (9500 и 11500); batch: `complete=false`, `export_blockers=["needs_review:F1"]`. ERROR допускается только если все трактовки дают одно доказанное исправление (навес внутр./внешн. → 450, `price_mismatch_all_interpretations`). Результат не зависит от порядка товаров в KB. Если названная цена подходит хотя бы одной трактовке — OK | `97caa0f` | `tests/intelligence/test_review_regressions.py` (F1), `test_api.py::test_review_f1_ambiguous_product_blocks_complete_export`; `docs/ai/evidence/review/f1_f3_before_after.json` |
| F2 P1 выбранные стороны кромки | 1200×1800, кромка по двум длинным: «Итого 18720» → ERROR 17280; «Итого 17280» → OK | 18720 → OK; 17280 → ERROR, correct 18720. Ассистент, инструмент `calculate_quote` и контроль диалогов строят вход одной функцией `pricing_input_for()` (стороны, количество, тип обработки); отдельной формулы нет. Проверены длинные/короткие, одна длинная, именованные стороны, все стороны, квадрат, количество > 1; неизвестная обработка или неуказанные стороны → итог не проверяется (NEEDS_REVIEW/без ложного ERROR) | `97caa0f` | то же (F2) |
| F3 P1 смешанные записи цен | «Итого 17 280 тг; цена за м²: 9000.» → OK (ставка 9000 не замечена) | ERROR, correct 8000. Цены с валютой и без объединяются без пересечений; число без валюты считается ценой только при ценовом слове в той же части фразы; размеры, толщины, артикулы и числа из названий позиций не считаются ценами. Проверены правильный итог с неверной ставкой, неверный итог с правильной ставкой, несколько цен, «₸/тг/тенге», пунктуация | `97caa0f` | то же (F3) |
| F4 live-приемка | `GLASSFLOW_AI_PROVIDER=none` + фиктивный `GLASSFLOW_GATEWAY_TOKEN` → `evaluation live` exit 0, 96/96, accuracy 1.0, все 252 ответа deterministic, p95 78 мс | exit 2, `live/live_status.json` status=BLOCKED (`profile_disabled` / `runtime_no_key`), 0 запросов к провайдеру; preflight одного реального вызова; пути deterministic/llm_tools/fallback/cache раздельно; в приемку идут только ответы `llm_tools` выбранной модели без cache hit; p95 модели — только по успешным вызовам выбранной модели (ошибки отдельно, очередь лимитера отдельно); статусы PASS/PARTIAL/FAIL/BLOCKED → exit 0/3/3/2; extended/holdout в гибриде помечены `live_acceptance=not_applicable`. Доработка по живому прогону: короткое охлаждение (лимит в минуту) выжидается перед следующим кейсом (≤ 90 с, вне задержки хода), дневная квота останавливает прогон, остаток — `not_run`, PASS невозможен | `781980b` + коммит статуса | `tests/intelligence/test_live_acceptance.py` (без сети: generate провайдеров подменен на исключение); `docs/ai/evidence/review/f4_live_acceptance_before_after.json` |

Изменение старого теста: `test_ambiguous_question_wrong_for_every_candidate_is_error` закреплял дефект F1 и заменен на `test_ambiguous_question_wrong_for_every_candidate_is_needs_review` (в тесте пометка со ссылкой на ревью). Holdout после первого прогона использовался для исправлений, поэтому его 36/36 — регрессионный, а не независимый результат (первый прогон 33/36 сохранен).

## Проверки (28.11.2026, Linux, Python 3.12.3, без ключей в окружении pytest)

| ID / команда | Фактический результат | Статус | Evidence |
|---|---|---|---|
| `env -u GEMINI_API_KEY -u OPENROUTER_API_KEY uv run pytest` | 296 passed, 3 skipped (было 249 на e83c211) | PASS | — |
| `uv run ruff check backend tests scripts infra/ai-gateway` | All checks passed | PASS | — |
| `uv run python scripts/check_foundation.py` | PASS | PASS | — |
| evaluation `open` — официальный неизмененный `selfcheck.py` | ассистент 36/36, **15.0 из 15**, выдумок 0; диалоги 8/8, **5.0 из 5**; exit 0 | PASS | evidence/open/report.json |
| `scripts/export_openapi.py` + `pnpm contracts:generate` + `git diff --exit-code packages/contracts` | без расхождений | PASS | packages/contracts |
| evaluation `extended` / `holdout` (гибрид) | 96/96 и 36/36 (holdout — регрессионный, первый прогон 33/36) | PASS детерминированным путем; `live_acceptance=not_applicable` | evidence/extended, evidence/holdout |
| `evaluation perf` | расчет p95 ≈ 6 мс, детерминированный ход p95 ≈ 25 мс | PASS локально; эталонный Windows — NOT RUN | evidence/perf/performance.json |
| `live-open --model gemini:gemini-3.5-flash-lite` | 18/18 ответов от выбранной модели, официальный selfcheck 15.0 из 15, 0 выдумок | **PASS** | evidence/live/open_live_gemini-3.5-flash-lite_v2.json |
| `live --cases broad --repeats 3` (24 кейса ×3, `ai_first`) | 70/72 от модели, 57/70 = 81,4%; критические 31/36 = 86,1%; 0 неподтвержденных утверждений по верификатору; ручная проверка — 3 реальные ошибки | **FAIL** (< 95%) → онлайн-путь не основной | evidence/live/live_primary_gemini-3.5-flash-lite_v2.json |
| `live --cases critical --repeats 3` после F4 | все ответы — детерминированный резерв: 429 `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, limit 500; повторная проверка 28.11 02:36 — квота все еще исчерпана (retryDelay ≈ 10,4 ч, сброс в полночь по тихоокеанскому времени ≈ 13:00 Asia/Qyzylorda) | **BLOCKED** | evidence/live/live_critical_x3_after_f4_quota_exhausted.json |
| Сравнение `gemini-3.6-flash`, критические ×3 | 1 ответ модели верный (E026 1988), затем 429: дневной лимит бесплатного уровня **20 запросов** | PARTIAL; модель непригодна для free tier | evidence/live/live_compare_gemini-3.6-flash_before_pacing.json |
| Ранняя остановка live-оценщика (после доработки) на реальной квоте | первый 429 дневной квоты → остановка, 35/36 `not_run`, лишних запросов нет, exit 2 | BLOCKED (ожидаемо) | evidence/live/live_gemini-3.6-flash_daily_quota_early_stop.json |
| Сравнение OpenRouter `nvidia/nemotron-3.5-super-vl:free` | 4/6 автомат, 6/6 по ручной проверке смысла; в 3–4 раза больше токенов | наблюдение | evidence/live/live_compare_openrouter_nemotron_v2.json |
| Режимы отказа в реальной сети | неверный ключ Gemini 400 → auth, OpenRouter 401, неизвестная модель, тайм-аут, 503/504, 429 дневной квоты, платная модель при free_only без сетевого вызова; ключ в сообщениях не утекает | PASS | evidence/live/failure_modes_live.jsonl |
| gateway: локальный процесс с ключом на сервере | приложение → `GatewayProvider` → шлюз → nemotron; 1988 = 1332 + 656 | PASS по HTTP localhost; HTTPS-хостинг — BLOCKED | evidence/gateway/local_process_smoke.json |
| `docker build -f infra/ai-gateway/Dockerfile .` | daemon недоступен | NOT RUN | — |
| `pnpm typecheck && pnpm test && pnpm build` | проходят на Node 22 (lock требует 24) | PASS (Node 22) | — |

### Primary tests (coverage.json)

| Тест | Статус | Основание |
|---|---|---|
| T21 | PASS (автомат) | test_api::test_t21 |
| T24 | PASS локальным путем (selfcheck 15/15) и онлайн-путем (`live-open` 15/15, все 18 от модели); UI-часть — C1 | evidence/open, evidence/live/open_live_… |
| T25, T26, T27, T29, T30, T31 | PASS | test_local_engine, test_pricing, test_api, test_dialog_quality |
| T28 | PASS (расчет/ревизии/количество, выбранные стороны после F2); подбор R006 на реальном плане — ожидает C2 | test_pricing, test_review_regressions |
| T32 | детерминированно PASS; онлайн-путь 24×3 — FAIL 81,4%; повтор критических ×3 — BLOCKED квотой | EVALUATION.md |
| T33 | PASS локально; живой LLM: навязанные цены не приняты, prompt не раскрыт (ручная проверка) | EVALUATION.md |
| T34 | PASS (mock + живые режимы отказа) | test_ai_resilience.py, failure_modes_live.jsonl |
| T35 | PASS (живой Gemini ↔ OpenRouter и через judge_gateway на localhost) | MODEL_SELECTION.md |
| T37, T38, T39 | PASS; F1–F3 исправлены | selfcheck 5/5; test_dialog_quality, test_review_regressions |

Support tests (моя часть): T03, T04, T05, T10, T23 (с тестовым портом), T36, T43, T49, T50/T52, T51, T53, T59 — PASS для модуля (см. предыдущие checkpoint'ы в git log). T60–T62: фактический расход живых прогонов записан в ECONOMICS.md; итог для economics.pdf — по прогону на ключе команды. T67 — лицензии в MODEL_SELECTION.md.

## План и результат

| Пункт | Статус | Evidence / commit | Что осталось |
|---|---|---|---|
| C3-01 Каталог, цены, mappings | реализовано, проверено | `3d370c1`, `5912e6b` | Pro: реальный `IntelligenceSources`, регистрация snippet миграции в Alembic |
| C3-02 Единый точный Pricing | реализовано, проверено; единый `pricing_input_for()` (F2) | `762b52c`, `97caa0f` | — |
| C3-03 AI-инструменты | реализовано, проверено; `find_remnants` не выдается модели при `inventory_mode=none` | `6e585f6` | реальные порты C2/Pro |
| C3-04 Диалог и проверка фактов | реализовано, проверено; верификатор отклоняет ложное «нет остатков» и «не выполняет доставку» | `6e585f6`, `5c67b40` | — |
| C3-05 Gemini и OpenRouter | реализовано, проверено вживую; цепочка `gemini-3.5-flash-lite` → `nemotron-3.5-super-vl:free` (при ключе) → `gemini-3.8-flash`; предохранитель 60 с, доля срока на модель, мгновенный переход в local при дневной квоте | `6cc73b9`, `762b52c`, `33ba311` | ключ проекта команды, повтор `check_ai(live=True)` |
| C3-06 Контроль диалогов и batch | реализовано, проверено; F1–F3 исправлены | `97caa0f` | Pro: run jobs, CSV-экспорт |
| C3-07 judge_gateway engine | реализовано, проверено локально; серверные профили инструментов | `91757d3`, `6cc73b9` | **BLOCKED**: HTTPS-хостинг, проверка с компьютера жюри; Dockerfile не собран |
| C3-08 Полная оценка | реализовано; live-приемка по F4 | `781980b`, `33ba311` | **BLOCKED**: повтор критических ×3 после сброса квоты; онлайн-путь FAIL на расширенных — нужны правила полноты итога |
| C3-09 Экономика и передача | реализовано, фактический расход живых прогонов | `5c67b40` | итоговые числа — прогон на ключе команды (Pro) |

## Контракты и интеграция

См. [docs/ai/INTEGRATION.md](../ai/INTEGRATION.md). API обратно совместим: новые поля только аддитивные (`reason_code` вердиктов, `tool_profile` запроса шлюза, `answer_paths`/`live_acceptance` в отчетах оценки). OpenAPI и `schema.d.ts` регенерированы стандартными командами, расхождений нет.

Запросы на изменение общих файлов (решает Pro):
1. Добавить `httpx>=0.28,<1` в группу `intelligence` `pyproject.toml` (сейчас транзитивно из google-genai).
2. По желанию перенести consumer-протоколы `InventoryPort/CrmPort/ScenarioPort/IntelligenceSources` в `ports.py`.
3. `QuoteRequest.quantity: int | None` — аддитивно.
4. `/settings/ai/check` → `service.check_ai`; AI-статус отдельным полем `/ready`.
5. Экспорт `verdicts.csv` не должен считаться полным при `export_blockers` (NEEDS_REVIEW после F1).
6. В профиль по умолчанию внести фактические лимиты проекта команды (`GLASSFLOW_AI_RPM/TPM/RPD`); тестовый проект показал 500 RPD на модель.

## Артефакты

- `docs/ai/evidence/review/{f1_f3_before_after.json,f4_live_acceptance_before_after.json}` — до/после по F1–F4.
- `docs/ai/evidence/live/` — `open_live_gemini-3.5-flash-lite_v2.json` (PASS), `live_primary_gemini-3.5-flash-lite_v2.json` (FAIL по правилам F4, пересчет в поле `acceptance_recomputed_with_f4_rules`), `live_compare_openrouter_nemotron_v2.json`, `live_chain_3.8-flash_to_flash-lite_before_breaker.json`, `live_critical_x3_after_f4_quota_exhausted.json` (BLOCKED), `failure_modes_live.jsonl`, `answers_live_gemini-3.5-flash-lite.csv`. Ключей и текстов запросов с ключами нет; прежний `live_status.json` (отсутствие ключа) удален как устаревший.
- `docs/ai/evidence/{open,extended,holdout,perf,gateway}/`.

## Внешние блокеры

| Блокер | Затронуто | Требуемое действие |
|---|---|---|
| Дневная квота free tier исчерпана: `gemini-3.5-flash-lite` 500/день, `gemini-3.6-flash` 20/день (тестовый проект); сброс ≈ 08:00 UTC | повтор `live --cases critical --repeats 3` на `gemini-3.5-flash-lite` | повтор после 08:00 UTC 28.11 (назначен; см. «Следующий шаг») или на ключе команды |
| Тестовые ключи владельца не релизные | итоговый model_id, economics.pdf | ключ бесплатного проекта команды в хранилище настроек → `check_ai(live=True)` → `evaluation live` |
| Нет хостинга для judge_gateway | C3-07 live, T54/T59/T62 по шлюзу | HTTPS-хостинг + секреты → `judge_gateway smoke` с нового компьютера |
| Нет docker daemon | Dockerfile шлюза | собрать образ на машине с Docker |
| Ветки C2/Pro не слиты | реальный подбор остатков, sources, CRM, settings/secret store, run jobs/CSV | интеграция по INTEGRATION.md |

## Следующий шаг

1. После сброса квоты (напоминание на 28.11 08:10 UTC): `uv run python -m glassflow.modules.intelligence.evaluation live --model gemini:gemini-3.5-flash-lite --cases critical --repeats 3` → обновить EVALUATION.md и этот статус. Без ключа/квоты статус остается BLOCKED.
2. Онлайн-путь (`ai_first`) остается FAIL на расширенных кейсах; чтобы сделать его основным, нужны правила верификатора на полноту итога (H016 — итог без кромки) и на ложное отсутствие позиции (E074), затем повторная оценка. До этого по умолчанию — гибрид.
3. Интегратор: сквозные шаги INTEGRATION.md 1–5, HTTPS-шлюз с компьютера жюри.

## Итоговый handoff

- Коммиты основной работы: `3d370c1`, `5912e6b`, `4616645`, `c97719b`, `91757d3`, `5004ba3`, `eca6013`, `1e6ad7a`, `803f7f8`, `e83c211` (проверен ревьюером).
- Живые проверки и исправления по ним: `6e585f6` (утверждения о наличии, gating `find_remnants`, клиент Gemini на вызов, тайм-ауты), `6cc73b9` (цепочка моделей по живым данным, профили инструментов шлюза), `762b52c` (предохранитель и доля срока, единый `pricing_input_for`).
- Исправления ревью: `97caa0f` F1–F3, `781980b` F4, `5c67b40` правило доставки верификатора и документы, `33ba311` fail-fast при дневной квоте и EVALUATION, затем коммит со статусом, batch-регрессией F1 и выжиданием/ранней остановкой live-оценщика (SHA сообщается в отчете).
- Воспроизведение: `uv sync --locked --all-groups`; `uv run pytest tests/intelligence`; `uv run python -m glassflow.modules.intelligence.evaluation open|extended|holdout|perf`; live — с ключом в окружении, см. EVALUATION.md; шлюз — `infra/ai-gateway/DEPLOYMENT.md`.
- НЕ выполнено: повтор критических ×3 после F4 (квота), развертывание шлюза по HTTPS, сборка Docker-образа, полная приемка продукта.

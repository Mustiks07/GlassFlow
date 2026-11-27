# Выбор моделей AI (C3-05, C3-08)

Дата проверки документации: **27.11.2026**. Названия, бесплатность и лимиты меняются; перед релизом повторить проверку (TZ §50). Живые проверки выполнены 27.11.2026 с **тестовыми бесплатными ключами владельца** (без billing; ключи только в окружении сессии, не в git) — см. раздел «Живая проверка». Ключ команды для релиза нужно перепроверить тем же порядком.

## Источники

| Источник | Что подтверждено |
|---|---|
| aistudio.google.com/docs/models (редирект с ai.google.dev/gemini-api/docs/models) | `gemini-3.8-flash` (Stable), `gemini-3.6-flash` (Stable), `gemini-3-flash-preview` (Preview), `gemini-3.5-flash-lite` (Stable), `gemini-3.1-flash-lite` (Stable), семейство `gemini-4-carbon/neon/hydrogen/argon`; `gemini-2.5-flash` устарела и с 01.12.2026 перенаправляется на `gemini-3.5-flash-lite` |
| aistudio.google.com/docs/pricing | Free of charge (вход и выход): `gemini-4-hydrogen`, `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite` (+ по сводке `gemini-3-flash-preview`, `gemini-3.1-flash-lite`); нет бесплатного уровня: `gemini-4-carbon`, `gemini-4-neon`, `gemini-4-argon`. Платные ставки: `gemini-3.8-flash` $0,75 / $3,75 за 1M вход/выход (до 31.12.2026), `gemini-3.5-flash-lite` $0,30 / $2,50, `gemini-4-hydrogen` $1,50 / $7,50. Free tier: «Content used to improve our products» |
| aistudio.google.com/docs/rate-limits | Лимиты бесплатного уровня для текстовых моделей публично не перечислены: «can be viewed in Google AI Studio». Лимиты относятся к проекту |
| aistudio.google.com/docs/models/gemini-3.8-flash, …/gemini-3.5-flash-lite | Function calling и Structured outputs: supported |
| openrouter.ai/api/v1/models (снимок 27.11.2026) | `:free` модели с `tools` и `response_format`: `google/gemma-4-31b-it:free`, `google/gemma-4-26b-a4b-it:free`, `nvidia/nemotron-3.5-super-vl:free`, `baidu/ernie-5.5-flash-preview:free` и др. |
| openrouter.ai/pricing, /collections/free-models | `:free`: 20 RPM и 50 запросов в день (1 000/день после покупки кредитов ≈$10); неудачные попытки тоже считаются |

## Живая проверка (27.11.2026, тестовые ключи)

| Модель | Наблюдение | Evidence |
|---|---|---|
| `gemini-3.5-flash-lite` | доступна; вызов p50 ≈ 1,0 с, p95 ≈ 2,8 с (315 успешных вызовов); корректные tool calls; 2 ответа 429 за весь прогон | `evidence/live/live_primary_gemini-3.5-flash-lite_v2.json` |
| `gemini-3.6-flash` | доступна, но вызов ≈ 10 с (thinking-токены); в пакетном прогоне ходы упирались в срок 90 с | ping в журнале сессии; прогон остановлен как искаженный лимитером |
| `gemini-3.8-flash` | 503 «high demand» и 504 «Deadline expired» во время проверки | `evidence/live/live_chain_3.8-flash_to_flash-lite_before_breaker.json` |
| `gemini-4-hydrogen` | 503 «high demand» во время проверки | ping в журнале сессии |
| OpenRouter `google/gemma-4-31b-it:free`, `gemma-4-26b-a4b-it:free` | 429 «temporarily rate-limited upstream» | ping в журнале сессии |
| OpenRouter `nvidia/nemotron-3.5-super-vl:free` | доступна; вызов p50 ≈ 4,7 с; в 3–4 раза больше токенов (reasoning); 4/6 по автоматическим критериям, 6/6 приемлемы по ручной проверке смысла | `evidence/live/live_compare_openrouter_nemotron_v2.json` |
| Режимы отказа (реальная сеть) | неверный ключ Gemini → 400 `API_KEY_INVALID` (классифицируется как auth), OpenRouter → 401; неизвестная модель → 404/400; тайм-аут 0,05 с → timeout; платная модель при free_only → policy без сетевого вызова; утечки ключа в сообщениях нет | `evidence/live/failure_modes_live.jsonl` |
| judge_gateway | локальный процесс шлюза с ключом OpenRouter на сервере: приложение → `GatewayProvider` → шлюз → nemotron; 1988 = 1332 + 656, AB1001 → менеджер; склад отклонен локальной валидацией | сессионный прогон (HTTP localhost, не HTTPS-хостинг) |

Выбор по фактам: **основная `gemini-3.5-flash-lite`**, межпровайдерный резерв `openrouter:nvidia/nemotron-3.5-super-vl:free` (если задан ключ OpenRouter), затем `gemini-3.8-flash`. Выбор относится к онлайн-пути; по умолчанию работает гибрид (распознанные запросы — детерминированно, модель — только для нераспознанных).

## Профиль по умолчанию (конфигурация, `providers/settings.py`)

- Режим `free_only`, бюджет 0, без платного fallback.
- Gemini (основной путь ТЗ): `gemini-3.5-flash-lite` → резерв OpenRouter `nvidia/nemotron-3.5-super-vl:free` (при ключе) → `gemini-3.8-flash`. Тайм-аут вызова 15 с, предохранитель выводит перегруженную модель из цепочки на 60 с, отказавшая основная модель получает только свою долю срока хода.
- OpenRouter (альтернатива): конкретный model_id; `openrouter/free` и `openrouter/auto` запрещены политикой (`OPENROUTER_FORBIDDEN_ROUTERS`).
- Кандидат ТЗ `gemini-4-hydrogen` в бесплатном списке, но не выбран по умолчанию без сравнительного теста (название не критерий качества).
- Список бесплатных моделей зашит как дата-зависимая конфигурация `GEMINI_FREE_TIER_MODELS` с датой проверки; при изменении тарифа его обновляют, а не обходят.

Важно: `free_only` в приложении означает «не вызывать модели вне проверенного бесплатного списка». Если в проекте Google включен billing, запросы могут тарифицироваться — это проверяется в консоли проекта; приложение этого определить не может и показывает в настройках.

## Что осталось для итогового model_id

1. Ключ бесплатного проекта команды в защищенном хранилище настроек (тестовые ключи владельца не являются релизными).
2. `POST /settings/ai/check` (Pro) → `IntelligenceService.check_ai(live=True)` — доступность, фактическая модель, задержка.
3. `uv run python -m glassflow.modules.intelligence.evaluation live` — критические кейсы ×3 с записью модели, задержки, токенов, ошибок инструментов и оценки; затем сравнить `gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-4-hydrogen`, `google/gemma-4-31b-it:free` на одном наборе.
4. Зафиксировать выбранный model_id и prompt_version в RunManifest (Pro).

Практически: открытые 18/18 вопросов и 8/8 диалогов, расширенный и holdout набор проходят детерминированным путем без сетевых вызовов; модель нужна для нераспознанных формулировок. Поэтому выбор модели влияет на долю «понятых» свободных запросов, а не на числа (числа всегда из Pricing/KB).

## Компоненты и лицензии (T67, вклад модуля intelligence)

| Компонент | Назначение | Лицензия (по метаданным пакета/провайдера) |
|---|---|---|
| google-genai 2.34.0 | официальный SDK Gemini | Apache-2.0 |
| httpx 0.29.0 | HTTP-клиент OpenRouter и шлюза (транзитивно из google-genai) | BSD-3-Clause |
| FastAPI, Pydantic, SQLAlchemy, uvicorn | API, DTO, хранение, процесс шлюза | MIT / MIT / MIT / BSD-3-Clause |
| Alembic | только тест snippet миграции | MIT |
| Модели Gemini через API | генерация по API Google | условия Gemini API Terms; free tier — данные могут использоваться Google |
| Gemma 4 через OpenRouter (кандидат) | альтернативная бесплатная модель | Gemma Terms of Use + условия OpenRouter |

Передача прав на код компании — только по отдельному согласованию (R66); модуль не включает чужой код, кроме зависимостей из lock-файла.

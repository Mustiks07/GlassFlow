# Статус CLAUDE_3_MUSTAFA

Рабочий checkpoint агента. Foundation не означает готовность продукта; статусы ниже различают «реализовано», «проверено», «ожидает интеграции» и «заблокировано».

- Ветка: `codex/claude-3-mustafa-ai` (опубликована в origin).
- Foundation commit: `16d63c6`.
- Последний проверенный код-коммит: `803f7f8` (этот статус — следующим коммитом, см. `git log`).
- Последнее обновление: 27.11.2026.
- Общий статус: **READY FOR INTEGRATION** для детерминированного ядра (каталог, расчеты, диалог, контроль диалогов, шлюз-engine). **BLOCKED** — все живые сетевые проверки AI (нет ключа провайдера) и развертывание шлюза (нет хостинга). Полная приемка продукта не выполнялась (это задача интегратора).
- Миссия: [../agents/CLAUDE_3_MUSTAFA.md](../agents/CLAUDE_3_MUSTAFA.md). Подробности: [docs/ai/README.md](../ai/README.md).

## План и результат

| Пункт | Статус | Реализованное поведение | Evidence / commit | Что осталось |
|---|---|---|---|---|
| C3-01 Каталог, цены, mappings | реализовано, проверено | KB-парсер (имена/цены/NULL/единицы/правила, неизвестные поля как данные, версия sha256); `MaterialMapping` confirmed/proposed/ambiguous/unmapped с основанием и версией, подтверждение менеджером (expected_version, 409); API каталог/поиск/детали/версии/правила/mappings; Quote с ревизиями в общей БД; snippet миграции | `3d370c1`, `5912e6b`; tests/intelligence/test_catalog.py, test_api.py, test_migration_snippet.py | Pro: реальный `IntelligenceSources` из снимков и регистрация snippet в Alembic |
| C3-02 Единый точный Pricing | реализовано, проверено | Decimal; м² = мм²/1e6; кромка по подтвержденным сторонам (длинные/короткие по фактическим размерам); ROUND_HALF_UP по строкам, итог = сумма; лист и м² независимы; фурнитура розница/порог из KB; кромка 4 мм 300, 6 мм 400 из правила r4; фацет/пескоструй/прочие толщины → менеджер; 1988.00 / 1991.76 / 3976.00 / 3000 | test_pricing.py (вкл. Hypothesis 200 примеров) | — |
| C3-03 AI-инструменты | реализовано, проверено (mock) | 9 инструментов ТЗ + `get_rules`, `submit_answer`; строгие модели аргументов, ограниченный результат; неизвестный инструмент/битый JSON/неверные аргументы отклоняются до исполнения; склад/CRM/сценарии через порты; нет SQL/shell/HTTP/рассылки/оплаты/резерва | assistant/tools.py; test_ai_resilience.py | реальные порты C2/Pro на интеграции |
| C3-04 Диалог и проверка фактов | реализовано, проверено | извлечение намерения/товара/размеров (см/м → мм, неясные единицы → вопрос)/количества/обработки; уточнение по различающим атрибутам; многошаговый контекст; ответ 2–4 предложения из типизированных фактов + рабочая карточка; `verify_answer` (числа и обещания); лимит 6 итераций, deadline, кеш по содержимому и версиям; честный local_limited | assistant/{local,engine,llm,verifier}.py; test_local_engine.py | живой LLM-путь — BLOCKED |
| C3-05 Gemini и OpenRouter | реализовано, проверено (mock) | `AIProvider`; Gemini на google-genai (без авто-ретраев SDK и auto function calling, сохранение thought signatures); OpenRouter httpx (`allow_fallbacks=false`, usage.cost); judge_gateway-клиент; free_only (платная модель отклоняется до сети, роутеры `openrouter/free|auto` запрещены); 401/403 без повторов, 429 c Retry-After, 5xx/тайм-аут ≤2 повтора с backoff+jitter, затем проверенный бесплатный резерв; RPM/TPM/RPD/параллельность; журнал `intel_ai_call`; профиль из env + secret provider; `check_ai` | providers/*; test_provider_adapters.py, test_ai_resilience.py; docs/ai/MODEL_SELECTION.md | **BLOCKED**: проверка в аккаунте, выбор model_id по живым тестам |
| C3-06 Контроль диалогов и batch | реализовано, проверено | смысл числа (м²/лист/розница/от N шт/итог), размеры/толщина/коды не цены; эталон из того же Pricing; OK/ERROR/NEEDS_REVIEW (цена не подходит ни одному кандидату неоднозначного вопроса → ERROR с помеченным исправлением); допуск 0,5; batch вопросов и диалогов с статусом строки, sha256 входа, `complete`/`export_blockers`; KEY не читается | quality/dialogs.py; test_dialog_quality.py; selfcheck 5/5 | Pro: вызов из run jobs, CSV-экспорт |
| C3-07 judge_gateway engine | реализовано, проверено локально | отдельная app factory, закрепленные провайдер/модели/prompt/схемы; отзывные хешированные токены со сроком и квотой; лимиты тела/контекста/итераций, RPM токен/сессия/IP, дневной и денежный лимит; free_only до сети; маскированные логи; healthz/readyz; CLI serve/issue/revoke/smoke; Dockerfile-шаблон; DEPLOYMENT.md | `91757d3`; test_gateway.py (вкл. сквозной путь приложение→шлюз); evidence/gateway/local_process_smoke.json | **BLOCKED**: HTTPS-хостинг, ключ, холодный старт, проверка с компьютера жюри; Dockerfile не собран (нет docker daemon) |
| C3-08 Полная оценка | частично | команда оценки; 18/8 через runtime + неизмененный selfcheck; 96 расширенных + 36 holdout синтетических кейсов | `c97719b`; docs/ai/EVALUATION.md, evidence/ | **BLOCKED**: критические ×3 реальным профилем, сравнение кандидатов, p95 AI |
| C3-09 Экономика и передача | реализовано (без факт. расхода) | формат журнала, учет вызовов/повторов, квоты free tier, тарифы с датой/источником, формулы, оценка размера контекста; handoff | docs/ai/ECONOMICS.md, INTEGRATION.md | фактический usage — после живого прогона |

## Проверки

| ID / команда | Вход / среда | Фактический результат | Статус | Evidence |
|---|---|---|---|---|
| `uv run pytest` | Linux, Python 3.12.3 | 248 passed, 3 skipped (foundation 7 + intelligence, включая параметризованный прогон по всем позициям KB) | PASS | — |
| `uv run ruff check backend tests scripts infra/ai-gateway` | — | All checks passed | PASS | — |
| `uv run python scripts/check_foundation.py` | — | 14 inputs, 66/67 coverage, PDF hash | PASS | — |
| `pnpm typecheck && pnpm test && pnpm build` | Node 22.23.5 (lock требует 24 — предупреждение engine) | tsc ok, 2 tests, build ok | PASS (на Node 22) | — |
| `pnpm contracts:generate && git diff --exit-code packages/contracts` | после `scripts/export_openapi.py` | без расхождений | PASS | packages/contracts |
| evaluation `open` (T24, T37) | KB sha256 f464c67f…, selfcheck sha256 dc3118a6… | ассистент 36/36, **15.0/15**, выдумок 0; диалоги **5.0/5**; exit 0 | PASS | evidence/open/report.json; answers.csv sha256 ab4e6122…, verdicts.csv db4fa089… |
| evaluation `extended` (T32) | 96 синтетических | первый прогон 77/96 (18 ложных срабатываний оценщика + 2 дефекта); после исправлений 96/96, 0 неподтвержденных утверждений | PASS (детерминированный путь) | evidence/extended |
| evaluation `holdout` (T32) | 36 синтетических, написаны до запуска | **первый прогон 33/36 (91,7%)**, 0 неподтвержденных; после 3 исправлений 36/36 | первый прогон ниже 95% — зафиксировано | evidence/holdout/holdout_report_FIRST_RUN.json |
| шаблонный прогон по всем 47 позициям KB | test_template_sweep.py | все шаблоны вопросов и диалогов проходят (3 пропуска — нет цены за м²) | PASS | tests/intelligence |
| evaluation `perf` | Linux-контейнер | расчет p95 6,19 мс (цель 300); детерминированный ход p95 24,7 мс | PASS локально; эталонный Windows — NOT RUN | evidence/perf/performance.json |
| evaluation `live` | нет ключа | — | BLOCKED | evidence/live/live_status.json |
| gateway local smoke | uvicorn 127.0.0.1, HTTP, без ключа | healthz 200 (212 мс), readyz 503, turn 503 PROVIDER_NOT_CONFIGURED | ожидаемый честный отказ; HTTPS — BLOCKED | evidence/gateway/local_process_smoke.json |
| `docker build -f infra/ai-gateway/Dockerfile .` | docker CLI есть, daemon нет | не выполнено | NOT RUN | — |

### Primary tests (coverage.json)

| Тест | Статус | Основание |
|---|---|---|
| T21 | PASS (автомат) | test_api::test_t21 — подтвержденная ревизия неизменна, новая KB → stale → ревизия 2 с diff |
| T24 | PASS локальным путем (selfcheck 15/15 + ручная проверка смысла в EVALUATION.md); UI-часть — C1 | evidence/open |
| T25 | PASS | test_local_engine (AB1012, AB1020, фацет, пескоструй, сроки, скидка), группы unknown_price |
| T26 | PASS | 10 000 vs 20 000 не смешаны; складское соответствие `ambiguous` → уточнение |
| T27 | PASS | лист 170 000, деталь неизвестна, `unmapped`; после уточнения 3 000 |
| T28 | PASS (расчет/ревизии/количество); подбор R006 на реальном плане — ожидает C2 | test_pricing, test_local_engine, test_api |
| T29 | PASS | 99/100 шт, NULL bulk, лист не делится на площадь |
| T30 | PASS (автомат) + ручная проверка формулировки совместимости | test_local_engine::test_t30 |
| T31 | PASS | перестановка/новые ID/тот же ID с другим текстом |
| T32 | детерминированно PASS (≥95% на итоговых наборах, 0 обещаний); первый holdout 91,7%; повтор ×3 реальным профилем — BLOCKED | EVALUATION.md |
| T33 | PASS локально; живой LLM — NOT RUN | eval injection, test_t33 |
| T34 | PASS на mock-провайдерах; live — NOT RUN | test_ai_resilience.py |
| T35 | PASS на mock; live — BLOCKED | test_t35 |
| T37, T38, T39 | PASS | selfcheck 5/5; test_dialog_quality |

Support tests (моя часть): T03 (некорректная KB → 422 с причиной) PASS; T04 (изоляция наборов, одинаковые ID) PASS; T05 (новая цена в рабочей копии не меняет подтвержденное) PASS; T10 (точный material_id через явное соответствие) PASS; T23 (перепроверка остатка перед подтверждением, кандидат снят) PASS с тестовым портом — с реальным C2 ожидает интеграции; T36 (без сети: расчеты и детерминированные ответы, режим `local_limited`) PASS; T43 (смена клиента не переносит предложение) PASS; T49 (helper цены карточки 30–70% после округления) PASS; T50/T52 (новые ID; без KEY официальные баллы не считаются — оценщик запускает selfcheck только при наличии KEY) PASS для модуля; T51 (UTF-8 без BOM, точные заголовки в оценщике) PASS — итоговый экспорт Pro; T53 (одна упавшая строка не скрывает остальные) PASS; T59 (нет ключей/KEY в runtime) PASS статическими тестами; T60–T62 — evidence качества/стоимости частично, живые замеры BLOCKED; T67 — лицензии компонентов в MODEL_SELECTION.md; T01, T46, T58 — вклад модуля нейтрален, проверяет владелец.

## Контракты и интеграция

См. [docs/ai/INTEGRATION.md](../ai/INTEGRATION.md): сборка `IntelligenceService`, 22 маршрута, DTO, коды ошибок, порты (предоставляемые: `IntelligencePort`, batch, `check_ai`, valuation; потребляемые: `InventoryPort`, `CrmPort`, `ScenarioPort`, `IntelligenceSources`), миграция `intelligence_0001`, экспорт answers/verdicts, поля для UI.

Fixture-only/bootstrap: `PackDirectorySources` (набор `open-pack` из исходного пакета, origin `dev_pack_bootstrap`) используется роутером, только если платформа не положила сервис в `app.state.intelligence_service`. Тестовые двойники (`tests/intelligence/fakes.py`, фейковые порты склада) — только в tests.

Запросы на изменение общих файлов (решает Pro):
1. Добавить `httpx>=0.28,<1` в группу `intelligence` `pyproject.toml` (сейчас транзитивно из google-genai).
2. По желанию перенести consumer-протоколы `InventoryPort/CrmPort/ScenarioPort/IntelligenceSources` в `ports.py`.
3. `QuoteRequest.quantity: int | None` — аддитивно (None = неизвестно).
4. `/settings/ai/check` → `service.check_ai`; AI-статус отдельным полем `/ready`.
5. Платформенный idempotency middleware может заменить встроенную проверку confirm.

## Артефакты и источники

- `docs/ai/evidence/open/{answers.csv,verdicts.csv,report.json}` — оценочные CSV открытого набора (не конкурсный экспорт), отчет со stdout/exit selfcheck и хешами входов.
- `docs/ai/evidence/extended/extended_report.json`, `holdout/holdout_report.json`, `holdout/holdout_report_FIRST_RUN.json`, `perf/performance.json`, `live/live_status.json`, `gateway/local_process_smoke.json`.
- Синтетические наборы: `backend/glassflow/modules/intelligence/evaluation/cases_extended.json`, `cases_holdout.json` (происхождение указано в файлах).
- Документация моделей проверена 27.11.2026 (страницы Google AI Studio и OpenRouter API, см. MODEL_SELECTION.md). Секретов в репозитории нет.

## Внешние блокеры

| Блокер | Затронуто | Проверено независимо | Требуемое действие |
|---|---|---|---|
| Нет ключа Gemini/OpenRouter | C3-05 live, C3-08 live ×3, T32 (повтор), T33/T34/T35 live, T62, p95 AI, выбор model_id | все детерминированные и mock-контрактные проверки | ключ бесплатного проекта в хранилище настроек → `check_ai(live=True)` → `evaluation live` |
| Нет хостинга для judge_gateway | C3-07 live, T54/T59/T62 по шлюзу | engine, токены, лимиты, сквозной ASGI-путь, локальный процесс | HTTPS-хостинг + секреты → `judge_gateway smoke` с нового компьютера |
| Нет docker daemon | Dockerfile шаблона | — | собрать образ на машине с Docker |
| Ветки C2/Pro не слиты | реальный подбор остатков, sources снимков, CRM-порт, settings/secret store, run jobs/CSV | контракт через тестовые порты | интеграция по INTEGRATION.md |
| Локально Node 22 вместо 24 | frontend-проверки | typecheck/test/build проходят на 22 | повторить на Node 24 в CI |

## Следующий шаг

При появлении ключа: `uv run python -m glassflow.modules.intelligence.evaluation live` и сравнение кандидатов из MODEL_SELECTION.md; затем фиксация model_id в профиле. Иначе — передача интегратору по INTEGRATION.md (сквозная проверка шагов 1–5).

## Итоговый handoff

- Коммиты: `3d370c1` ядро (KB, mappings, Pricing, matcher, локальный движок, контроль диалогов); `5912e6b` сервис, маршруты, хранение, провайдеры, цикл инструментов; `4616645` тесты устойчивости/адаптеров/API/KEY; `c97719b` оценщик, наборы, evidence и исправления; `91757d3` judge_gateway; `5004ba3` valuation helper, T23, ограничение контекста; `eca6013` документация docs/ai и статус; `1e6ad7a` шаблонный прогон по всем позициям KB, политика «без чисел при неизвестной запрошенной цене», цена кромки по правилу r4; `803f7f8` контроль диалогов: ERROR, если цена не подходит ни одному кандидату неоднозначного вопроса.
- Воспроизведение: `uv sync --locked --all-groups`; `uv run pytest tests/intelligence`; `uv run python -m glassflow.modules.intelligence.evaluation open|extended|holdout|perf`; шлюз — `infra/ai-gateway/DEPLOYMENT.md`.
- READY FOR INTEGRATION: детерминированный каталог/расчет/диалог/контроль диалогов, API, миграция, engine шлюза. НЕ выполнено: живые AI-проверки, развертывание шлюза, полная приемка продукта.

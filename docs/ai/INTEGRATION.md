# Интеграция модуля intelligence (для GPT Pro, Клауда первого, Клауда второго и интегратора)

## Сборка сервиса

Все потребители (HTTP, UI, AI-инструменты, конкурсный прогон, экспорт) используют один `IntelligenceService` (`backend/glassflow/modules/intelligence/service.py`).

```python
from glassflow.modules.intelligence.service import IntelligenceService, DbLedger
from glassflow.modules.intelligence.providers.settings import build_runtime, profile_from_env
from glassflow.modules.intelligence.assistant.prompts import PROMPT_VERSION

runtime = build_runtime(profile, secret_provider, prompt_version=PROMPT_VERSION, ledger=DbLedger(session_factory))
app.state.intelligence_service = IntelligenceService(
    sources,            # IntelligenceSources: KB/materials снимка набора (Pro dataset repository)
    session_factory,    # общий sessionmaker платформы
    inventory=cutting,  # объект с find_candidates(FindRequest) -> Candidates (CuttingPort C2 подходит)
    crm=crm_port,       # rank(RankRequest) -> Ranking; draft_reminder(ReminderRequest) -> Reminder (Pro)
    scenario=None,      # compare(dataset_id, base_plan_id, change) -> dict (C2/Pro jobs), опционально
    runtime=runtime,    # None → честный local_limited
)
```

Если `app.state.intelligence_service` не задан, роутер собирает bootstrap-вариант: `PackDirectorySources` (исходные KB и materials.csv открытого пакета как набор `open-pack`, источник `dev_pack_bootstrap`), общий session factory, AI из переменных окружения. Это точка запуска до готового импорта Pro, а не замена dataset repository.

`IntelligenceSources` (`sources.py`): `knowledge_base(dataset_id, version=None) -> SourceDocument`, `kb_history(dataset_id)`, `materials(dataset_id)`. Новая KB рабочей копии = новая версия в истории; старые подтвержденные предложения сохраняются (T21).

## Маршруты (`/api/v1`)

| Метод и путь | DTO | Примечание |
|---|---|---|
| GET `/catalog?dataset_id&kb_version?&kind?` | `list[CatalogProduct]` | цены строками/NULL, attributes, unknown_fields, mapping |
| GET `/catalog/search?dataset_id&q` | `CatalogSearchResult` | exact/best/ambiguous/not_found + уточнение |
| GET `/catalog/products/{id}?dataset_id` | `CatalogProduct` | |
| GET `/catalog/versions?dataset_id` | `list[PriceVersion]` | версии KB (sha256), current |
| GET `/catalog/rules?dataset_id` | `list[CatalogRule]` | правила KB с темами |
| GET `/catalog/mappings?dataset_id` | `list[MaterialMapping]` | confirmed/proposed/ambiguous/unmapped, версия, основание |
| POST `/catalog/mappings/{id}/confirm` | `MappingConfirmRequest → MaterialMapping` | expected_version, 409 при конфликте |
| POST `/quotes`, `/quotes/calculate` | `QuoteRequest → Quote` | сохраняет ревизию 1; inventory_mode опционально |
| GET `/quotes/{id}?dataset_id&revision?` | `Quote` | `stale=true`, если KB изменилась |
| GET `/quotes/{id}/revisions?dataset_id` | `list[Quote]` | |
| POST `/quotes/{id}/revise` | `QuoteReviseRequest → Quote` | expected_revision, changes, reprice_current_kb; diff |
| POST `/quotes/{id}/confirm` | `QuoteConfirmRequest → Quote` | `Idempotency-Key`; повтор того же тела → тот же ответ, другое тело → 409; needs_review/устаревшая KB → 409; перепроверка остатка |
| POST `/quotes/{id}/cancel` | `QuoteCancelRequest → Quote` | |
| POST `/quotes/dimensions/normalize` | `DimensionNormalizeRequest → DimensionNormalizeResult` | см/м → мм, неоднозначные единицы |
| POST `/assistant/turns` | `AssistantTurn → AssistantReply` | контекст в `intel_conversation`, предложение по диалогу ревизуется |
| GET `/assistant/conversations/{id}?dataset_id` | `Conversation` | |
| POST `/assistant/batch` | `AnswerBatchRequest → AnswerBatchResult` | для run job вопросов |
| GET `/assistant/ai-status` | `AIProfileView` | без сети и секретов |
| GET `/assistant/usage?since?` | dict | сводка журнала для экономики |
| POST `/quality/check` | `DialogRequest → DialogVerdict` | |
| POST `/quality/batch` | `DialogBatchRequest → DialogBatchResult` | NEEDS_REVIEW → `complete=false`, `export_blockers` |

Ошибки — единый `ApiError {code, message_ru, field_errors, conflict_objects, retryable, correlation_id}`: 404 `DATASET_NOT_FOUND`/`QUOTE_NOT_FOUND`/`PRODUCT_NOT_FOUND`, 409 `STALE_KB_VERSION`/`REVISION_CONFLICT`/`ALREADY_CONFIRMED`/`QUOTE_NOT_CONFIRMABLE`/`VERSION_CONFLICT`, 422 `VALIDATION_ERROR`/`MATERIAL_NOT_FOUND`/`KB_INVALID`.

## Порты, которые модуль предоставляет

- `IntelligencePort` (`ports.py`): `service.quote(QuoteRequest) -> Quote` (= calculate_quote), `await service.check_dialog(DialogRequest) -> DialogVerdict`.
- Пакетные операции для run coordinator Pro (вызываются в job, не через HTTP): `await service.answer_questions(AnswerBatchRequest)` и `service.check_dialogs(DialogBatchRequest)`. Каждая строка несет статус, путь ответа, модель, sha256 входа; падение одной строки не скрывает остальные.
- AI-настройки: `service.ai_profile()`, `await service.check_ai(AICheckRequest(profile, live))` — для `POST /settings/ai/check` Pro (ключ не возвращается).
- Оценка материала для C2/Pro (отдельная цель, не каталог): `valuation.material_replacement_valuation(area_mm2, rate)` и `valuation.remnant_card_price(length, width, rate, factor)` с проверкой 30–70% после округления.

## Экспорт (Pro P-08)

- `answers.csv`: `id,answer` из `AnswerBatchResult.answers` в исходном порядке; `answer` уже готовый текст (обычные пробелы как разделитель тысяч, десятичная запятая — совместимо с selfcheck).
- `verdicts.csv`: `id,verdict,correct` из `DialogBatchResult.verdicts`; для OK `correct` пустой; `correct` — строка без валюты (`"10000"` или `"1991.76"`). Строки `NEEDS_REVIEW` в CSV не превращать в OK/ERROR: `complete=false` → частичный статус модуля.
- Офлайн-проверка формата и баллов на открытом наборе: `uv run python -m glassflow.modules.intelligence.evaluation open`.

## Миграции

`modules/intelligence/migrations/intelligence_0001.py` — `upgrade(op)`/`downgrade(op)` без собственной Alembic-ревизии. Таблицы: `intel_quote_revision`, `intel_mapping_override`, `intel_conversation`, `intel_turn`, `intel_ai_call`, `intel_quality_check` (модели в `models.py` на общем `Base`; foundation `create_all` уже создает их).

## Запросы на изменение общих контрактов (Pro решает)

1. `pyproject.toml` группа `intelligence`: явно добавить `httpx>=0.28,<1` (сейчас приходит транзитивно из google-genai; нужен адаптеру OpenRouter и клиенту шлюза).
2. `ports.py`: при желании перенести consumer-протоколы `InventoryPort`, `CrmPort`, `ScenarioPort` из `modules/intelligence/ports_consumed.py` и `IntelligenceSources` из `sources.py`; семантика описана в docstring.
3. `QuoteRequest.quantity` стал `int | None` (None = количество неизвестно: для фурнитуры показываются обе ставки). Существующие вызовы с int не меняются.
4. `/ready`: держать AI отдельным полем (`runtime.status`), не влияющим на readiness ядра.
5. Idempotency middleware Pro может заменить встроенную проверку confirm (ключ и хеш тела хранятся в `intel_quote_revision`).

## Для интерфейса (Клауд первый)

`AssistantReply`: `answer` (2–4 предложения клиенту), `status` (answered/clarification/manager_handoff/limited), `mode` (online/local_limited) + `ai_unavailable_reason`, `answer_path` (deterministic/llm_tools/fallback), `verifier_status`, `card` (подтвержденные параметры, допущения, недостающие параметры, нормализованный размер, альтернативы, факты с источниками, needs_manager), `quote` (позиции, `total_tg` или `known_subtotal_tg` + `unknown_components`, `stale`, `inventory_status`, `candidate_refs` с местом), `tool_calls` (для раскрываемых технических деталей). Деньги — строки; отображать с ₸ и разделителями.

## Сквозная проверка после слияния (интегратор)

1. `uv run pytest tests/intelligence` и foundation-проверки.
2. Сборка сервиса с реальными sources Pro и `CuttingPort` C2 → POST `/quotes` 450×370 clear-6 с `inventory_mode=free_whole_remnants` → кандидат из реального плана; 451×370 → пересчет 1991.76; confirm → перепроверка версии остатка.
3. Конкурсный run: вопросы/диалоги нового набора → `answer_questions`/`check_dialogs` → CSV Pro → `selfcheck.py` на открытом наборе (15/15, 5/5).
4. AI: ключ в хранилище → `check_ai(live=True)` → `evaluation live` ×3 → журнал `/assistant/usage`.
5. judge_gateway: `infra/ai-gateway/DEPLOYMENT.md`, smoke с нового компьютера по HTTPS.

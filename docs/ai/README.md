# AI, каталог и расчеты GlassFlow (модуль Клауда третьего)

| Документ | Содержание |
|---|---|
| [INTEGRATION.md](INTEGRATION.md) | сборка сервиса, маршруты, порты, экспорт, миграции, запросы на изменение общих контрактов |
| [EVALUATION.md](EVALUATION.md) | результаты 18/8 через runtime + selfcheck, расширенный и holdout наборы, история, NOT RUN |
| [MODEL_SELECTION.md](MODEL_SELECTION.md) | кандидаты Gemini/OpenRouter с источниками и датой, политика free_only |
| [ECONOMICS.md](ECONOMICS.md) | журнал расхода, число вызовов, квоты, сценарная стоимость |
| [../../infra/ai-gateway/DEPLOYMENT.md](../../infra/ai-gateway/DEPLOYMENT.md) | judge_gateway: запуск, env, защита, ротация, smoke |
| `evidence/` | отчеты прогонов (JSON/CSV), без ключей и без содержимого KEY |

## Как устроено

1. KB → `catalog/kb.py`: исходные названия, цены, NULL, неизвестные поля как данные, версия = sha256.
2. Явные соответствия `CatalogProduct → Material` (`catalog/mapping.py`): `confirmed` только при идентичном названии, форматы листа — `proposed`, остальное `unmapped/ambiguous`; подтверждение менеджером версионируется.
3. Единый точный расчет `pricing.py` (Decimal, ROUND_HALF_UP по строкам, итог = сумма строк).
4. Диалог: детерминированное понимание запроса (`catalog/matching.py`, `nlu/extract.py`) → факты из Pricing/KB → короткий ответ (`assistant/local.py`). Онлайн-модель (`assistant/llm.py`) подключается только для нераспознанных запросов, работает через строгие инструменты (`assistant/tools.py`), ее текст проходит `verify_answer`.
5. Провайдеры (`providers/`): Gemini (google-genai), OpenRouter (httpx), judge_gateway; free_only, лимиты, повторы, резерв, журнал.
6. Контроль диалогов (`quality/dialogs.py`): смысл числа в ответе менеджера и эталон из того же Pricing.

Быстрая проверка: `uv run pytest tests/intelligence` и `uv run python -m glassflow.modules.intelligence.evaluation open`.

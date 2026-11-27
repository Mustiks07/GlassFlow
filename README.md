# GlassFlow

Рабочее место менеджера KSM: **запрос клиента → проверенный расчет → подходящий остаток → следующее действие → проверяемый результат**.

**Состояние репозитория: общая база разработки.** Запускаются интерфейс, API и SQLite. Бизнес-модули предстоит реализовать четырем агентам; предметные API сейчас возвращают явный `501 FEATURE_NOT_IMPLEMENTED`. Это не готовая конкурсная поставка.

## Агентам: начать здесь

| Агент | Ветка | Полное задание |
|---|---|---|
| Клауд первый, Ильяс | `codex/claude-1-ilyas-ui` | [Интерфейс, E2E, покупатели, презентация](docs/agents/CLAUDE_1_ILYAS.md) |
| Клауд второй, Мырзабек | `codex/claude-2-myrzabek-cutting` | [Склад, геометрия, раскрой](docs/agents/CLAUDE_2_MYRZABEK.md) |
| Клауд третий, Мустафа | `codex/claude-3-mustafa-ai` | [Каталог, расчеты, AI и контроль ответов](docs/agents/CLAUDE_3_MUSTAFA.md) |
| GPT Pro Мустафы | `codex/gpt-pro-mustafa-platform` | [Платформа, CRM, аналитика, экспорты, сборка](docs/agents/GPT_PRO_MUSTAFA.md) |
| Отдельная финальная сессия GPT Pro | создаст `codex/integration` после завершения четырех веток | [Интеграция и окончательная приемка](docs/agents/GPT_PRO_INTEGRATOR.md) |

Это полные назначения до результата, а не стартовые пакеты. [Порядок совместной работы](docs/agents/README.md), [правила владения файлами](AGENTS.md), [все 66 требований и 67 проверок](docs/agents/COVERAGE.md).

## Основание проекта

- [Полное ТЗ, 51 страница](docs/specification/GlassFlow_Development_Specification_v1.pdf) и [текст для агентов](docs/specification/GlassFlow_Development_Specification_v1.txt).
- [Исходный кейс](inputs/Case_KSM_Steklo_dengi_klient.pdf), [пакет организаторов](inputs/PACK_for_teams/README.txt), [контрольные суммы исходников](docs/specification/input_manifest.json).
- [Архитектура и контракты](docs/architecture/CONTRACTS.md), [реестр всех обязательных API-операций](docs/architecture/API_OPERATIONS.md).
- Исследовательские результаты находятся в `analysis/cutting`, `analysis/crm`, `analysis/review`. Это ориентиры на открытых данных; runtime не должен читать готовые ответы или evaluation KEY.

## Запуск для разработчиков

Нужны Python **3.12**, Node.js **24**, **uv** и **pnpm 11.25.0**. Команды выполняются из корня репозитория. Python и Node версии закреплены в `.python-version` / `.node-version`.

```sh
uv sync --locked --all-groups
pnpm install --frozen-lockfile
```

Первый терминал:

```sh
uv run uvicorn glassflow.main:app --host 127.0.0.1 --port 8000
```

Второй терминал:

```sh
pnpm dev
```

Открыть **http://127.0.0.1:5173**. Документация API: **http://127.0.0.1:8000/docs**. SQLite создается в `.runtime/`. Frontend проксирует `/api` на 8000. После `pnpm build` backend также обслуживает собранный интерфейс на 8000 (перезапустить backend после сборки).

Для каркаса AI-ключ не нужен. Пример будущих настроек — `.env.example`; автоматическое чтение `.env` пока не реализовано. Ключи нельзя коммитить. Gemini/OpenRouter подключает назначенный агент; модель и доступность бесплатной квоты проверяются на реальном аккаунте.

## Проверка базы

```sh
uv run ruff check backend tests scripts
uv run pytest
uv run python scripts/check_foundation.py
pnpm typecheck
pnpm test
pnpm build
```

Проверяются старт, честная readiness, SQLite, строгие mm-типы, OpenAPI, целостность исходников и полнота распределения ТЗ. Это **не** 67 приемочных тестов продукта: их фактический статус пока `not_run`.

После согласованного изменения DTO владелец контрактов выполняет:

```sh
uv run python scripts/export_openapi.py
pnpm contracts:generate
```

Общий backend — модульный монолит. `backend/glassflow/modules/` разделен по владельцам; `packages/contracts/` содержит OpenAPI и TypeScript-схему. Frontend, AI-инструменты и экспорты обязаны использовать одни и те же предметные сервисы.

## Готовность конкурсной версии

Ее подтверждает отдельная интеграционная сессия после слияния четырех веток: реальные сценарии, новые входные данные, пять точных CSV одного run, офлайн-ядро, живой AI при наличии ключа, EXE на чистой Windows и проверенные открываемые жюри материалы. Скриншоты заглушек и исследовательские результаты не заменяют эту приемку. Первое место и результат на скрытых данных заранее не гарантируются.

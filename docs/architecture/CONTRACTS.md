# Общая архитектура и контракты

## Стек и состояние базы

Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, SQLite WAL; React 19 + TypeScript + Vite; Node 24, pnpm 11.25.0, uv. Точные версии зависимостей фиксируют `uv.lock` и `pnpm-lock.yaml`. SciPy/OR-Tools — инструменты solver; Gemini SDK — один адаптер провайдера. Архитектура продукта — локальный модульный монолит с фоновым worker, а не набор независимо запускаемых микросервисов. Исключение — при необходимости защищенный AI gateway для конкурсного запуска.

В foundation реально работают SQLite bootstrap, `/health`, `/ready`, frontend shell, OpenAPI и тесты. Предметные маршруты намеренно отвечают **501 FEATURE_NOT_IMPLEMENTED**. Bootstrap `create_all` заменяет Pro на Alembic до предметной поставки. Переключать readiness на ready до реальной проверки обязательных функций запрещено.

## Поток данных

`immutable inputs → import preview/validation → dataset snapshot → domain services → versioned run → validator → exact export`.

Интерфейс и AI tools вызывают одни и те же сервисы. Ни frontend, ни LLM, ни экспортер не рассчитывают заново предметные цены/геометрию/приоритеты. Research scripts используются как источник проверок и воспроизводимых ориентиров; приложение не запускает research-файлы как движок и не читает готовые open-ответы для новых данных.

## Владение границами

| Граница | Реализация | Потребители |
|---|---|---|
| Dataset repository, snapshot, jobs, transactions, settings, audit | GPT Pro | все |
| Inventory availability, independent geometry validator, solve, reserve/consume/release | Claude 2 | UI, AI, sales, runs |
| Catalog/KB, Decimal quote, dialog quality, AI adapters/tools | Claude 3 | UI, CRM, runs |
| CRM ranking, local reminders, manager metrics | GPT Pro | UI, AI |
| Buyers repository, sale cards, run assembly, CSV/PDF | GPT Pro | UI; C1 supplies buyer evidence |
| UI/e2e, real buyer research, slides | Claude 1 | platform, integration |

Python `backend/glassflow/ports.py` фиксирует начальные Protocol; Pydantic DTO находятся в feature-owned `contracts/*.py`. Порты расширяются владельцем общей сборки по описанным в handoff потребностям, без скрытой смены смысла существующих полей. Pro предоставляет dependency injection/registry сервисов; feature routers не создают собственную БД/планировщик. Доменные сервисы принимают репозитории/UoW, поэтому их можно реализовать и тестировать независимо от незавершенной соседней ветки.

## Обязательные инварианты

- Любая предметная сущность, импорт, план, предложение, напоминание и прогон привязаны к `dataset_id`; одинаковые внешние ID из разных наборов не смешиваются. Исходный набор неизменяем; рабочая копия и contest run выделены явно.
- Размеры — строго целые миллиметры; денежные значения в JSON — десятичные строки, вычисления через Decimal, округление только по правилам ТЗ. Unknown не превращается в 0. Каталог SKU не равен material_id, mapping хранится явно с версией/основанием.
- Замеры, резерв, прайс, план, quote и subject напоминания имеют версии. Mutations требуют expected_version/revision; несовпадение возвращает 409 и перечень конфликтов. Двойное подтверждение не удваивает резерв/расход.
- Pro реализует idempotency middleware/service: `Idempotency-Key` для commit/confirm/consume/export; scope — dataset+operation+key, сохраняются request hash, результат и статус. Тот же key с другим body → 409. Повтор идентичного body возвращает исходный результат.
- Одна transaction охватывает проверку версий, резерв/списание, изменение предметного состояния, audit и idempotency result. C2 реализует правила inventory, Pro — UoW/SQLite concurrency. Вложенный сервис не делает самостоятельный commit.
- Read-only AI availability не резервирует кусок. Quote/example не означает подтвержденную продажу. Cards/reminders повторно проверяют источник при создании, открытии и подтверждении. Просроченные ссылки получают stale, не молчаливую подмену.
- Геометрия: edge 5 mm, gap 3 mm, premium без дефектов, материал точный, закаленное стекло целиком с допуском ±2 mm, никаких виртуальных дочерних остатков в пяти обязательных карточках.
- Lock assignment фиксирует только назначение; lock placement фиксирует назначение+координаты+поворот. Search status `optimal_in_pool` не означает глобальный оптимум. Отсутствие свободного целого куска не доказывает невозможность перепланирования.
- Runtime запрещено читать evaluation KEY/labels из исходного пакета. Import preview явно отделяет разрешенные runtime источники от evaluation-only. Оценка на labels — отдельный offline evaluation command, без утечки в ranking/AI prompt.

## Jobs, solver, отмена

Pro владеет durable job queue, состояниями queued/running/completed/failed/cancelled/interrupted, worker process и SQLite writer. C2 предоставляет синхронный `solve(snapshot, JobContext)` и независимую validate. Progress/incumbent — сообщения, а не запись в пользовательскую БД из worker. Публиковать incumbent можно только после валидации. Cancel проверяется в ограниченных интервалах; сохраняется последний допустимый результат. Нельзя превращать interrupted в completed после рестарта.

RunManifest должен включать dataset/hash manifest, config_version, plan_id/revision, KB version, buyer registry version, ranking policy/model version, seed/time budget/threads, provider/model/prompt version, duration, status, validation report, files/hashes. CSV создаются из одного run; частичный прогон имеет partial/blocked и перечень отсутствующего. Full export не выдает успех при NEEDS_REVIEW в обязательных ответах.

## HTTP, ошибки и схемы

Префикс `/api/v1`. OpenAPI создается из FastAPI; `packages/contracts/schema.d.ts` генерируется openapi-typescript. Синхронизация: `uv run python scripts/export_openapi.py`, затем `pnpm contracts:generate`. Foundation покрывает основные маршруты; дополнительный обязательный список — `API_OPERATIONS.md`.

Генерировать `openapi.json` и `schema.d.ts` разрешено каждому агенту после изменений его DTO/routes, несмотря на общее владение `packages/contracts` у Pro. Ручные правки запрещены. При merge conflicts интегратор повторяет генерацию из объединенного backend; иначе snapshot-тест неизбежно устареет на предметной ветке.

Ошибки: `{code,message_ru,field_errors,conflict_objects,retryable,correlation_id}`. Foundation оборачивает 501; Pro должен унифицировать validation 422, 404/409/413/429/503 и unexpected 500 (без секретов/stacktrace). Списки в foundation невелики; Pro/C2 согласуют additive cursor/filter support до больших наборов, без потери dataset scope. Сервер привязан к loopback; Pro добавляет защиту локальных destructive endpoints, Origin checks и ограничение upload/archive paths.

Frontend не использует fixtures в рабочем запуске; test fixtures — только tests. Пока backend недоступен, показывается понятное состояние и повтор, не fabricated data. Feature agents проверяют свои ports на in-memory test repositories, а реальная интеграция проверяет общую SQLite transaction.

## Замороженная Windows-сборка

Pro отвечает за PyInstaller, включение frontend dist и native SciPy/OR-Tools, writable data dir, singleton/port probing, launcher/browser, controlled shutdown/backup/restore, health/readiness и диагностику. Сначала frozen smoke worker, затем полная упаковка. Интегратор отдельно проверяет чистую Windows; наличие `.exe` само по себе не является PASS. API-ключи не входят в EXE/JS; network-free core остается работоспособным, режим local_limited маркируется честно.

## Бесплатный AI

`GLASSFLOW_AI_MODE=free_only` по умолчанию. Provider/model выбираются конфигурацией из реально доступных в аккаунте; не обещать неизменность free quotas. C3 реализует timeouts, bounded retries, backoff 429, JSON schema validation, tool allowlist, injection defenses, audit без PII, explicit opt-in paid fallback. Pro интегрирует settings, budgets и launch/gateway config. При отсутствии ключа offline checks выполняются, live provider test остается blocked с точной причиной.

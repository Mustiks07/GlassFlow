# Работа четырех агентов GlassFlow

Цель — реализовать все ТЗ единым локальным продуктом Windows с честными проверенными результатами, а не четыре раздельных демонстрации. Эта директория содержит полные задания; владельцам не нужно запрашивать продолжение после каждого этапа.

| Агент | Владелец | Ветка | Полная миссия |
|---|---|---|---|
| Клауд первый | Ильяс | codex/claude-1-ilyas-ui | [CLAUDE_1_ILYAS.md](CLAUDE_1_ILYAS.md) |
| Клауд второй | Мырзабек | codex/claude-2-myrzabek-cutting | [CLAUDE_2_MYRZABEK.md](CLAUDE_2_MYRZABEK.md) |
| Клауд третий | Мустафа | codex/claude-3-mustafa-ai | [CLAUDE_3_MUSTAFA.md](CLAUDE_3_MUSTAFA.md) |
| GPT Pro | Мустафа | codex/gpt-pro-mustafa-platform | [GPT_PRO_MUSTAFA.md](GPT_PRO_MUSTAFA.md) |
| Финальный GPT Pro | отдельная сессия | отдельная integration branch от main | [GPT_PRO_INTEGRATOR.md](GPT_PRO_INTEGRATOR.md) |

## Как начать

Открой репозиторий и checkout указанную ветку. Прочитай AGENTS.md, ТЗ, архитектуру, свою миссию и соответствующий docs/status файл. Проверь foundation перед первой правкой. Сначала реализуй свои contracts и сервисные точки подключения, затем выполняй весь backlog. Незавершенная зависимость не повод останавливаться: работай с согласованным портом и изолированным тестом, отметив необходимость реальной интеграции.

Ветка каждого агента начинается с одного foundation. Ни один из четырех агентов не сливает работу в main. Финальная сессия объединяет ветки и исправляет интеграционные дефекты, затем проверяет реальную конкурсную поставку.

## Владение и швы

- C1: весь apps/web, frontend manifest и pnpm lock, browser E2E, визуальное качество, публичные buyer evidence, слайды и резервные визуалы.
- C2: backend/glassflow/modules/cutting, backend/glassflow/contracts/cutting.py, tests/cutting.
- C3: backend/glassflow/modules/intelligence, backend/glassflow/contracts/intelligence.py, tests/intelligence; AI evaluation и gateway engine/deploy templates в infra/ai-gateway/** и evidence в docs/ai/**.
- Pro: platform/core/main, modules/platform, modules/crm, modules/sales; contracts/platform.py, crm.py, common.py; tests/platform, crm, sales; platform assembly, DB/migrations, pyproject/uv.lock, CI, infra кроме infra/ai-gateway/**, экспорт, Windows packaging, экономика и examples PDF.
- backend/glassflow/ports.py и API_OPERATIONS.md задаются foundation и принадлежат Pro. Потребители не меняют семантику молча. Запросы на общий контракт записываются в status; Pro/интегратор применяет согласованный итог.
- Root pnpm lock редактирует C1. Python dependency manifest/uv lock редактирует Pro. Доменные зависимости заложены в foundation; дополнительные зависимости запрашиваются с обоснованием, а не добавляются конкурирующими lock-файлами.
- C2/C3 могут добавить только свои module/migrations snippets. Pro регистрирует все snippets в единой истории и тестирует свежую БД/upgrade.
- HTTP и AI используют одни бизнес-сервисы. CSV/PDF используют результаты этих сервисов, не собственные вычислители.
- C1 производит buyers evidence и проверяемый CSV-кандидат; Pro валидирует, хранит, подбирает покупателей и выпускает финальный buyers_top50.csv.
- C3 производит gateway engine и deploy templates в infra/ai-gateway/**; Pro — прочая infra и deployment integration, C3 — реальные AI smoke/evaluation, интегратор — запуск с компьютера жюри.
- C1 оформляет питч, C2 предоставляет проверенные solver metrics, C3 — AI quality/cost evidence, Pro — run/economics/examples. Финальные числа берутся из одного фактического run.

## Общие интеграционные сценарии

1. Импорт → неизменный snapshot → рабочая копия → точная цена → доступный остаток → явное подтверждение → одна атомарная резервация.
2. Изменение размера/замера/цены → новая ревизия → пересчет и объяснимый diff → stale у зависимых предложений, карточек и задач.
3. CRM 25 заявок → группировка клиентов → явно выбранный адресат → локальное напоминание без изменения заказчика.
4. Конкурсный run → независимые модули → финальный план → пять свободных оригинальных остатков → пять согласованных CSV.
5. Перезапуск/сбой/отключение сети → сохраненные подтвержденные данные, честная частичная готовность и ограниченный AI режим.
6. Windows EXE на чистом компьютере → реальные UI/backend/worker → подключенный AI gateway без провайдерского секрета в публичном пакете.

## Checkpoints и завершение

Каждый агент обновляет только свой docs/status файл. Записи содержат commit, входные хеши, задачи, команды и результаты проверок, артефакты evidence, внешние блокеры и следующий шаг. Честно отмечай NOT RUN, FAIL, BLOCKED, READY FOR INTEGRATION. PASS ставится только по фактически выполненной проверке. Тесты с человеческим присутствием/будущим конкурсным временем не получают PASS за написанный скрипт.

Финальный интегратор проверяет отсутствие потерянных требований, реальные API вместо fixtures, секреты/KEY, новые ID, миграции, официальный validator, документы и фактически открываемую поставку. Главное условие завершения — работающий единый продукт по ТЗ; сумма четырех отчетов сама по себе этого не доказывает.


## Разрешенное исключение: generated contracts

Каждый агент может регенерировать packages/contracts/openapi.json и packages/contracts/schema.d.ts стандартными командами репозитория после изменения DTO. Это явное исключение из файлового ownership: ручные правки generated файлов запрещены. Семантика domain DTO остается у domain-владельца, common DTO и ports — у Pro. При merge conflict интегратор заново генерирует оба файла из объединенных Python DTO, а не выбирает произвольную сторону. Не оставляй foundation OpenAPI snapshot gate сломанным после своих DTO changes.

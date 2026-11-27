# GlassFlow

Рабочее место менеджера KSM: запрос → проверенный расчет → остаток → следующее действие → проверяемый результат.

**Статус этой ветки: реализована платформа, готовится интеграция C1/C2/C3. Полный конкурсный продукт еще не принят.**
Имя команды: **TEAM_NAME_REQUIRED** — команда должна задать его до выпуска финального README.

В `codex/gpt-pro-mustafa-platform` работают импорт, SQLite, неизменная история, CRM, аналитика, локальные задачи,
процессная очередь, manifest, строгий экспорт завершенных частей, backup/restore, настройки и Windows launcher.
Cutting, pricing/assistant/QA и UI принадлежат другим веткам. Их отсутствие дает явные 501/503/failed dependency,
а не выдуманный результат. `/api/v1/ready` сообщает `degraded` до фактической регистрации и проверки всех сервисов.

## Запуск из исходников

Нужны Python **3.12**, Node **24**, uv и pnpm **11.25.0**; версии закреплены lock-файлами.

```powershell
uv sync --locked --all-groups
pnpm install --frozen-lockfile
pnpm build
uv run python -m glassflow.launcher
```

Launcher выбирает свободный адрес `127.0.0.1`, дожидается БД/миграций/worker и открывает браузер.
Данные сохраняются в `%LOCALAPPDATA%/GlassFlow`; `GLASSFLOW_DATA_DIR` явно задает другой локальный каталог.
Повторный процесс не открывает вторую БД. Автообновления отключены.

Для разработки API: `uv run uvicorn glassflow.main:app --host 127.0.0.1 --port 8000`.
UI в отдельном терминале: `pnpm dev`; адрес [127.0.0.1:5173](http://127.0.0.1:5173).
Swagger: [API docs](http://127.0.0.1:8000/docs). Собранный UI также обслуживается backend.

## Windows без Python и Node

```powershell
./scripts/build_windows.ps1
uv run python scripts/smoke_frozen.py
uv run python scripts/scan_release.py dist/GlassFlow
```

Результат — `dist/GlassFlow/GlassFlow.exe` (оконное приложение без консоли), `GlassFlowDiagnostics.exe` (CLI-проверки) и соседние файлы; переносится вся папка.
Для менеджера: распаковать подготовленный ZIP и открыть EXE. Сейчас это проверенный **platform smoke bundle**,
не финальная конкурсная поставка: C1/C2/C3 еще не объединены. Проверка на чистом компьютере без автора остается NOT RUN;
обещание полного запуска <=5 минут пока не подтверждено.

[Фактический frozen smoke](docs/release/frozen-smoke.json) проверяет SciPy/OR-Tools в дочернем EXE, импорт,
CRM job, скачанный CSV, штатное завершение и сохранность после повторного запуска.
Измерения относятся только к указанной в отчете build-машине, не к чистой Windows 11.

## Свои данные и API

Сначала открыть `GET /api/v1/session` либо приложение: локальная сессия устанавливает cookie. `POST /api/v1/datasets/demo` с Idempotency-Key открывает неизмененный учебный комплект из поставки; это реальные исходные данные, не зашитые ответы.
Для owner-only настроек/backup/restore/shutdown нужен возвращенный `X-GlassFlow-Session`.
Токен локальной сессии не является ключом провайдера и не передается покупателям.

1. `POST /api/v1/imports/preview`: multipart `files` (семь файлов) или `file` (ZIP).
2. Исправить построчные errors; `POST /imports/{id}/commit`, JSON name/mode, заголовок `Idempotency-Key`.
3. Рабочая копия: `POST /datasets/{id}/working-copy`. KB history/head: `GET/POST /datasets/{id}/kb` (file + expected_version + Idempotency-Key). Исходник остается неизменным. Предметные операции явно передают dataset_id.
4. `POST /crm/rank`, `GET /analytics/managers`, API локальных reminders доступны без сети.
5. `POST /runs`: immutable исходник, config_version, modules. Ответ 202 содержит job_id и run_id.
6. `GET /jobs/{id}`, cancel/retry; `GET /runs/{id}`; `POST /runs/{id}/export` с Idempotency-Key.

Обязательные типы: materials, stock, orders, applications, questions, dialogs, KB. CSV — comma/UTF-8;
BOM распознается, оригинальные байты/SHA сохраняются. ZIP ограничен 50 МиБ распакованных данных и 1000 entries;
до 100000 строк в одном CSV. Ошибки и неизвестные материалы не удаляются молча. Evaluation KEY/служебные ответы
не поступают в runtime. Для пяти новых файлов добавляются исходные materials/KB; конкурсный run фиксирует именно их.
Чужие server paths из UI не принимаются. История защищена append-only SQLite triggers.

Экспорт: UTF-8 без BOM, ровно заданные колонки и ID, пять файлов из одного run; buyers_top50 отдельно.
`NEEDS_REVIEW`, чужие ревизии карточек и неготовые зависимости блокируют full-ready. Готовые части скачиваются
с явным partial manifest. Экспорт не рассчитывает цены/ответы заново; solution проверяет неизмененный validate.py.

## CRM и напоминания

Зафиксирована `reference-v1`: stable sort(-прошлых_заявок, жалоба, manager==M4, дней_с_последнего_контакта),
затем 25 app_id. UI получает сгруппированных клиентов и объяснения; приоритет не называется вероятностью.
На открытых данных baseline дает 20/25; результат закрытого набора неизвестен.

[Оценка logistic candidate](docs/release/crm/evaluation.json) содержит 13 одинаковых для baseline/model splits
(client-group, temporal purge 60 дней, random control) и train-only tuning. На одном temporal split модель хуже;
она не promoted. Неизвестная жалоба сохраняется NULL и при равенстве сортируется после известных. JSON candidate имеет hash/список признаков; пользовательские pickle/joblib не загружаются.

Адресат reminder отличается от заказчика quote. Due_at — реальный UTC timestamp, не синтетический день_года.
Specific-remnant и quote_example требуют актуальной проверки C2/C3 через порт; без него 503.
При изменении источника задача/карточка получает stale; внешних email/WhatsApp и рассылок нет.
M1–M5/unknown показывают исходные строки, знаменатели, полноту и NULL, отдельно paid average и среднюю всех заявок.
Ответ_через_мин — задержка, не активный труд. Метка возврата означает новое обращение за 60 дней, не покупку.

## AI, расходы и ограничения

По умолчанию `local_limited`, Gemini как основной provider setting, `free_only`, paid_enabled=false, бюджет 0.
Конкретный model_id/реальная квота не заявлены проверенными. OpenRouter — альтернативный адаптер C3.
Ключ задается через owner settings и хранится только в памяти сессии; не возвращается в ответах и не пишется в БД/JS/EXE.
После рестарта его нужно ввести заново. Для платного профиля необходимы явное включение и положительный бюджет.
RPM/TPM/RPD, retries, timeout, tool/output limits передаются адаптеру; доступность аккаунта проверяется отдельно.

`judge_gateway` требует HTTPS и отзывной judge token; серверный provider key в Windows не поставляется.
[Gateway integration](infra/judge-integration/README.md): engine C3 опубликован отдельно; объединение и реальный hosting/endpoint/токен еще не выполнены,
поэтому live-AI и маршрут жюри BLOCKED. Локальная CRM/аналитика/импорт от сети не зависят.

Фактическая месячная стоимость полного продукта пока неизвестна: нужны AI usage/quota, hosting и support.
Нулевой default budget не является обещанием бесплатной работы любого объема.
Экономика требует финального раскроя/baseline и минимум 10 измеренных пар активного времени;
[генератор и формулы](docs/economics/README.md) не выдают исследовательские ориентиры за факт.
[Examples](docs/examples/README.md) выпускаются только из реальных результатов, синтетический preview не включается в поставку.

## Проверки и источники

```powershell
uv run ruff check backend tests scripts
uv run pytest
uv run python scripts/check_foundation.py
pnpm typecheck
pnpm test
pnpm build
uv run python scripts/export_openapi.py
pnpm contracts:generate
```

Эти проверки и platform tests не равны 67 приемочным сценариям всего продукта.
Для source-копии релизной папки, где намеренно нет evaluation KEY: `scripts/check_foundation.py --runtime-source`.
Исходный Git сохраняет полный неизмененный пакет, и обычный integrity check проверяет его целиком.
[ТЗ](docs/specification/GlassFlow_Development_Specification_v1.pdf), [контракты](docs/architecture/CONTRACTS.md),
[операции](docs/architecture/API_OPERATIONS.md), [handoff платформы](docs/release/PLATFORM_HANDOFF.md).

Стек: Python/FastAPI/Pydantic/SQLAlchemy/Alembic/SQLite; SciPy/OR-Tools; scikit-learn; ReportLab;
React/TypeScript/Vite. [Python metadata/licenses](docs/release/python-licenses.json),
[frontend licenses](docs/release/frontend-licenses.json). Metadata inventory не заменяет юридическую проверку;
передача прав KSM требует отдельного согласования команды.

## Первая неделя пилота

День 1: менеджер подтверждает каталог, materials mapping, ставки и места. День 2: цех проверяет технологические
ограничения отдельно от конкурсной геометрии. День 3: парные измерения реальных расчетов и активного времени.
День 4: локальная очередь клиентов под контролем менеджера. День 5: фактические расходы, удобство и решение
о дальнейшем пилоте/общем сервере. Исторический Precision@25 не считается измеренным приростом выручки.

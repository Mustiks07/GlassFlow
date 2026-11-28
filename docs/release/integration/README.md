# GlassFlow — общая рабочая версия Vtiposhniki

28 ноября 2026. Это проверка объединенного продукта, не подтверждение полной конкурсной приемки.
Авторская история четырех веток и локальные документационные коммиты сохранены.
Точный ход, SHA и команды: [статус интегратора](../../status/GPT_PRO_INTEGRATOR.md).

## Настоящие результаты

В [open-run](open-run/integration-report.json) сохранены скачанные через HTTP пять CSV, buyers и manifest
одного run `3f2b0c7c-4fc0-49ed-8af3-9366d37fb3d0`. Runtime backend `6399ace`, исходная KB сохранена побайтно.
Весь прогон614,969 с на Windows10/12 logical CPUs, solver extended600 с/7 workers/seed42.
Покрытие59,0831595%, invalid=missing=0, 200/298 деталей, 42/110 полностью покрытых заказов,
142 использованных и58 свободных исходных кусков. Замещенный материал1 019 398,20 ₸ по исходному прайсу.
Это плановая материальная оценка; фактический расход появляется только после отдельного подтверждения.

Неизмененные официальные selfcheck после завершения приложения: ассистент36/36, диалоги8/8,
CRM20/25 (80%, reference baseline80%). Runtime не читает evaluation KEY. Это открытая проверка local_limited,
не live модель и не оценка закрытого набора. Пять карточек относятся к выбранному плану и пяти свободным
исходным кускам; у каждой три разных покупателя с сохраненными объяснениями и допущениями размеров.

[Quick baseline](baseline/integration-report.json) на тех же исходниках: 55,8080067%, 960 645,25 ₸,
16,563 с весь прогон, бюджет solver5 с. Extended добавил3,2751528 процентного пункта и58 752,95 ₸
материальной оценки. Это сравнение двух алгоритмических профилей, не человеческого труда и не прибыли.

[Changed-input run](changed-input-run/integration-report.json): новые ID во всех пяти CSV, обратный порядок строк,
длины склада+7 мм/деталей+1 мм, измененный вопрос451×370, CRM без меток возврата. Все пять выходов ready,
геометрия valid; баллы N/A, поскольку для этих данных нет официального KEY. Отдельная регрессия намеренно
неразрешимого диалога подтверждает partial export четырех готовых частей без выдуманного verdicts.csv.

## Воспроизведение

```powershell
uv sync --locked --all-groups
pnpm install --frozen-lockfile
pnpm build
# Отдельный процесс, новый изолированный каталог данных:
$env:GLASSFLOW_DATA_DIR='.runtime/reproduce'
uv run uvicorn glassflow.main:app --host 127.0.0.1 --port 8000
# Второй терминал:
uv run python scripts/run_integrated_open.py --profile extended --budget 600 --output .runtime/open
uv run python scripts/run_integrated_open.py --changed-inputs --profile quick --budget 5 --output .runtime/changed
```

Browser `product.spec.ts` требует отдельной свежей БД. `integrated-workflows.spec.ts` создает собственные
рабочие копии. `GLASSFLOW_E2E_URL=http://127.0.0.1:8000`, затем `pnpm --filter @glassflow/web e2e:real`
и `pnpm --filter @glassflow/web e2e:integration`. Fixture59 проверяет только UI и не заменяет эти сценарии.
`uv run pytest -o addopts='' -q` проверяет домены и общую composition; full report476 PASS/4 SKIP,
новая регрессия смены прайса/владельца проверена отдельно. Причины SKIP зафиксированы в XML.

Native: после стабильного production build выполнить `uv run pyinstaller --noconfirm packaging/GlassFlow.spec`,
`uv run python scripts/smoke_frozen.py --report docs/release/integration/frozen-smoke.json`,
`uv run python scripts/scan_release.py dist/GlassFlow`. Smoke проверяет именно EXE и его process worker,
реальные C2/C3 quote/reserve/handover/consume, отмену поиска с сохраненным incumbent, restart и restore.
Переносится вся папка `dist/GlassFlow`, а не один EXE. Отчет относится к машине сборки, не к чистой Windows11.
Окончательный EXE: build_commit `ba32194`, SHA256 `785ec45a662d9d5e201d97a24709da9e15dad4a3b9cb54a0185e896647d8385d`.
На нем отдельно прошли10+2 настоящих browser E2E, затем принудительный kill/restart/retry
([native-recovery](native-recovery.json)). После переноса в версионную папку снова проверены старт,
импорт исходного пакета и реальный frozen C2 solver ([portable-check](portable-check.json)).
[Package manifest](package.json) содержит путь ZIP, размер и хеш; CRC проверен, scanner PASS на исходной и перенесенной папке.

## Границы

[Матрица R/T/F](acceptance.json) различает автоматические свидетельства, partial, blocked и not_run.
[Проверка покупателей](BUYER_REVIEW.md) не утверждает подтвержденного интереса организаций.
Коммерческие утверждения C3 связаны с товаром, единицей, ролью цены и количеством через доверенные references;
совпадение числа больше не разрешает произвольную цену. Оплата по умолчанию выключена.

Не закрыты: новая live оценка≥95% и критические повторы с ключом/квотой команды; реальный HTTPS gateway
и отзывной токен жюри; чистая Windows11 без dev tools; минимум10 пар человеческих трудозамеров;
финальные economics/examples PDF, обновленная презентация и репетиция; закрытый набор и будущая подача.
Существующая шестистраничная презентация C1 открыта и просмотрена: читается, но содержит placeholders
финального run и старые цифры/скриншоты. Она сохранена как черновик, не подменена и не названа финальной.
Ночные исследовательские функции не реализовывались.

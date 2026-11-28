# Экономика: источник чисел и условия выпуска

`economics.pdf` еще не выпущен: нет финального C2 run и сопоставимого проверенного baseline,
десяти фактических пар ручного/прикладного активного времени и выбранных командой расходов.
Исследовательские 1 017 742,15 / 117 888,85 не являются константами генератора.

Реализация: `backend/glassflow/modules/platform/reports.py`, `scripts/build_reports.py`.
Генератор требует actual ready RunManifest, минимум 10 разных labor_studies с protocol/observer/measured_at,
определенными началом/концом и measured manual_active_seconds/app_active_seconds. Положительная задержка
ответа CRM не используется как труд. Синтетические данные запрещены для final reports.

Формулы economics-v2: Δ материала = (итог - baseline) × monthly_dataset_multiplier × material_use_fraction;
труд = median(manual_seconds - app_seconds) / 3600 × monthly_operations × hourly_rate_tg;
чистый сценарный эффект = Δ материала + труд - AI - hosting - support;
окупаемость = implementation / эффект только при эффекте > 0.
Это сценарная оценка, а не выручка, прибыль или измеренный uplift CRM. Карточки не считаются продажами.

В evidence JSON раздел `economics` содержит decimal strings:
final_material_value_tg, baseline_material_value_tg, monthly_dataset_multiplier, monthly_operations,
hourly_rate_tg, ai_monthly_tg, hosting_monthly_tg, support_monthly_tg, implementation_tg.
Обязательны baseline_validation_ref/final_validation_ref, baseline_description, hourly_rate_basis,
monthly_volume_basis, implementation_basis и ai_cost_basis. Любая неподтвержденная стоимость подписывается
сценарным допущением; бесплатная квота не объявляется подтвержденной без реального теста C3.

AI basis включает фактические input/output/reasoning токены, retries/verifier, тариф и дату/курс/источник;
хостинг отдельно. Ставка часа - источник либо явное допущение команды.

После получения evidence:

```powershell
uv run python scripts/build_reports.py --evidence actual-report-evidence.json --output output/reports --font C:/Windows/Fonts/arial.ttf
```

PDF должен занимать ровно одну страницу. Финальные файлы отрендерить Poppler, открыть все страницы,
сверить числа с тем же run и только затем указать visual_review=passed в report-build.json.
Макет проверен синтетическим preview, который не является economics.pdf для жюри.

## U07: сценарий для интерфейса и PDF

Контракт: `docs/architecture/UPGRADE_CONTRACTS_v1_1.md`, Python DTO `contracts/economics.py`.
Чистая формула перенесена в `modules/platform/economics.py`; HTTP и PDF используют ее напрямую.
POST `/api/v1/economics/scenarios`, PUT `/{id}` с expected_version и Idempotency-Key;
GET `/{id}?dataset_id=&version=` и `/{id}/pdf?dataset_id=&version=` читают ту же историческую версию.
Для C1: показывать результаты backend, не пересчитывать их в JS. Hash inputs/result и formula_version совпадают.

У замера обязательны operator/observer, task_input_ref, оба result refs, timezone start/finish timestamps,
active seconds внутри elapsed time, число ошибок и rework seconds (уже включены в active time).
`measurement_status=supplied_measurements` означает данные пользователя, не независимую верификацию;
`synthetic` не допускается в финальную записку даже при подмене внешнего флага evidence.

`material_use_fraction` и basis — явное допущение доли использования прироста. Подтвержденное использование
value+ref, потенциальная продажа и фактическая выручка+ref — отдельные поля; они не суммируются с net.
Sensitivity: low/high объемов, ставки часа, доли; считаются углы диапазонов и min/max парной экономии.
Это диапазон сценариев, не доверительный интервал. При net<=0 окупаемость null, PDF пишет, что она не определена.

HTTP PDF помечен сценарным, competition_release_eligible=false; final builder по-прежнему требует ready same-run.
Положительный и отрицательный synthetic PDF скачаны через actual API, отрендерены Poppler и просмотрены:
одна страница, кириллица/значения/таблица/hash без обрезания. `.qa/u07-preview` не входит в конкурсный пакет.

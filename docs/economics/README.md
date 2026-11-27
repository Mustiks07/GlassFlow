# Экономика: источник чисел и условия выпуска

`economics.pdf` еще не выпущен: нет финального C2 run и сопоставимого проверенного baseline,
десяти фактических пар ручного/прикладного активного времени и выбранных командой расходов.
Исследовательские 1 017 742,15 / 117 888,85 не являются константами генератора.

Реализация: `backend/glassflow/modules/platform/reports.py`, `scripts/build_reports.py`.
Генератор требует actual ready RunManifest, минимум 10 разных labor_studies с protocol/observer/measured_at,
определенными началом/концом и measured manual_active_seconds/app_active_seconds. Положительная задержка
ответа CRM не используется как труд. Синтетические данные запрещены для final reports.

Формулы: Δ материала = (итог - baseline) × monthly_dataset_multiplier;
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

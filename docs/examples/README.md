# Проверяемые примеры

Отдельный настоящий [examples.pdf](../release/audit/final-series-a0afb4b-v2/reports/examples.pdf) выпущен из принятого EXE run на неизменённом открытом наборе:6 просмотренных страниц,3 примера каждой группы. Экономика ему не требуется (`--only examples`). Это не официальная закрытая сдача.
Не используется исследовательский solution, таблица ответов по ID или выдуманные напоминания.

Общий evidence JSON для `scripts/build_reports.py` содержит:

- `manifest`: actual ready RunManifest, run_id/dataset_id/input_hash/source_hashes.
- `economics`: нужен только для выпуска economics.pdf/обоих документов; для `--only examples` отсутствует.
- `examples.cutting`: минимум 3 фактические схемы: remnant_id, length_mm/width_mm,
  description, placements с part_id/x_mm/y_mm/rot/length_mm/width_mm. Геометрия не рассчитывается
  генератором: он только рисует проверенные координаты C2 и дает таблицу под схемой.
- `examples.answers`: минимум 3 question/answer из C3, с evidence reference.
- `examples.reminders`: минимум 3 recipient_client_id/source_app_ids/subject_type/reason/text
  из сохраненных задач; аналогичная цена отделена от заказа адресата.
- `examples.quality`: минимум 3 client/manager/verdict/correct из реального QA сервиса C3.

Каждый пример дополнительно содержит dataset_id, run_id, source_ref. Все происхождение указывается
в самом PDF, различие snapshots не скрывается. Минимальный макет: 3 страницы схем, по странице
ассистента, напоминаний и QA; длинные таблицы продолжаются с повторным заголовком.

TrueType font с кириллицей встраивается в PDF. Шрифт выбирает команда с проверкой права использования;
Windows Arial не копируется в source/bundle. Синтетический pytest preview явно маркируется
«НЕ ДЛЯ СДАЧИ», не включается в release и не заменяет реальные примеры.

# A02: заранее заданный протокол

`A02_PROTOCOL.json` фиксируется commit до нового эксперимента. Четыре кандидата, допустимые признаки,
порог mean lift0.04, запрет ухудшения на любом temporal split и отдельный новый контроль обязательны.
Original open dataset уже полностью использован: новый seed/holdout не становится независимым контролем.
При его отсутствии вывод — оставить reference-v1 независимо от найденного exploratory преимущества.

Новые manager-holdout и переименование manager IDs — diagnostics переносимости, не новая приемка.
Future label доступен только evaluator; runtime выбирает25 app_id, повтор client_id разрешен.
Одинаковые train/test для всех кандидатов; imputer/scaler/encoder/C selection используют только train.
Проверка early day90 отдельно фиксирует training counts/классы, результат и manager stress.

Команда воспроизведения будет `uv run python scripts/compete_crm.py`.
Actual U07 paired labor measurements не выводятся из CRM return labels или response_minutes.

Протокол опубликован `f083b8e`. Результат `a02-comparison.json`:18 срезов evaluated, все кандидаты отклонены.
Primary mean lift: reference-no-manager +0.015, logistic-manager -0.020, logistic-no-manager -0.005;
worst temporal обеих logistic -0.44. Нового независимого контроля нет. Runtime reference-v1 сохранен.
Manager holdout/renaming — проверка устойчивости ассоциации, не причинная оценка работы менеджеров.

# Регламент сдачи: 29 ноября 2026, Астана (UTC+5)

Все события ниже — будущие, фактическая подача не выполнена этой сессией.

| Время | Действие команды | Evidence | Статус |
|---|---|---|---|
| До 10:00 | Pipeline/model/deps/final bundle и запас actual квоты проверены | release manifest, clean-machine report, C3 quota report | not_run |
| 10:00 | Получить только официально опубликованные 5 closed CSV | оригинальные bytes/SHA256 и actual receipt timestamp | future |
| 10:00–11:00 | Actual same-run -> validate -> скачать/открыть -> загрузить пять CSV в closed_run | validator stdout/exit, final hashes, guest downloads | future |
| До 11:00 | Создать файлы на Drive; 11:05 — предельный допуск, не основной план | реальные Drive creation timestamps, не local mtime | T63 not_run |
| До 12:00 | Подать ссылку через кабинет, проверить всем по ссылке, freeze содержимое | фактическое принятие ссылки и гостевой доступ | T64 not_run |
| До 14:00 | Финализировать только презентацию, <=6 слайдов | актуальные actual run цифры, резервный PDF | T65 / C1 not_run |
| 14:45–15:15 | Регистрация всей команды: Иманова 19, БЦ Деловой дом Алма-Ата, этаж 3, офис 301 | подтверждение самой команды; ноутбук/переходник | T66 not_run |
| 15:15–16:45 | Защита: 3 мин питч + 2 вопросы + 1 смена; live <=30 секунд включая M1–M5 | actual rehearsal и явка, не наличие checklist | not_run |

Корень: README.md, code/, economics.pdf (1 page), buyers_top50.csv, examples.pdf,
closed_run/{solution,sale_cards,answers,picks,verdicts}.csv; Windows bundle/report дополнительно.
Final package проверяется именно после скачивания гостем. После freeze code/артефакты не изменяются.

Публикация, внешние сообщения, принятие условий и передача прав не выполнялись автоматически.
T67: metadata inventory подготовлен, фактическая проверка лицензий и согласование передачи — not_run.

# Проверка публичного buyer evidence

28 ноября2026. Исходные C1 `buyers_candidate.csv` и `evidence.json` сохранены.
`scripts/convert_buyer_evidence.py` воспроизводимо создает отдельные platform CSV/JSON, сохраняет hashes
оригиналов, entity IDs, даты и происхождение. Структурная проверка API:50 уникальных организаций,
49 Астана,9 категорий, score в допустимом диапазоне. Структурный `verified` не означает спрос или продажу.

Для трех мебельных организаций независимо открыты публичные источники:
[CATRINE](https://catrine.kz/), [Astana MG](https://astanamg.kz/), [DalaSK](https://astana-mebel.kz/).
Подтверждена мебельная деятельность. `furniture_insert` и `mirror_interior` — объясненное предположение
о применении, а не утверждение сайта о закупке. Диапазон100×100–2000×1500 мм является явным инженерным
допущением интегратора; материал, толщина и конечный размер требуют согласования. Для каленого материала
резка не предполагается. Эти три профиля подходят пяти фактически выбранным свободным исходным кускам;
в API buyer_matches сохранены material/dimensions/application/source/assumptions и interest_confirmed=false.

Повторный HTTP/TLS прогон всех50 исходных URL:44 PASS,6 ошибки TLS, без отключения верификации сертификатов.
Полный сырой отчет — `data/buyers/integration-source-checks.json`. Проблемы B05 Clever Design, B28 Nudu,
B37 OldBoy, B39 Rixos, B40 World Class, B50 Hani. Их публичные страницы дополнительно открыты веб-инструментом,
что подтверждает существование/профиль, но не отменяет воспроизводимых TLS ошибок Python.

Проверенные альтернативы и исправления отдельного platform evidence:

- [Nudu](https://sxodim.com/astana/place/nudu): заведение Астаны; заменен проблемный source_url.
- [Rixos President Astana](https://all.accor.com/hotel/B1Q3/index.ru.shtml): официальный Accor; source_url заменен.
- [KHS HUB](https://sxodim.com/astana/place/khs-hub): профиль IT-бара; домашний домен возвращал постороннее содержимое, заменен.
- [Clever Design](https://cleverdesign.kz/): дизайн жилых/коммерческих интерьеров Астаны.
- [OldBoy](https://oldboybarbershop.com/astana/izumrud): барбершоп Астаны, Кунаева10.
- [World Class](https://www.worldclass.kz/): фитнес-клуб Астаны.
- [Hani](https://yandex.kz/maps/ru/org/hani_cakes_coffee/136694287285/): кофейня/кондитерская Караганды.

Независимая случайная десятка, seed20261128: B30 MANNA, B08 SENSATA, B47 KHS, B07 DreamArt,
B01 CATRINE, B41 Invictus, B26 NAVAT, B25 Qazaq Gourmet, B24 Green Mall, B36 La Bottega.
Страницы C1 по этим ID открыты веб-инструментом; названия, город и профиль соответствуют.
Дополнительно перепроверены B13 АстанаСтройДом, B19 Talan Towers, B31 Line Brew.
Деятельность сама по себе не подтверждает размеры проемов, потребность в конкретном стекле или интерес.

T47 остается PARTIAL: формат/уникальность/география и выборочная предметная проверка подтверждены,
полное независимое принятие всех50 и стабильная доступность всех источников не объявляются PASS.
Никакие сообщения организациям не отправлялись, контакты частных лиц не собирались.

# Исправления после независимого аудита c6b4b02

База c6b4b02; ветка codex/audit-c6b4b02-fixes, отдельный worktree GlassFlow-audit-fixes.
main и прежние EXE/ZIP сохранены. Входной ZIP/отчёт сохранены как данные аудита;
его команды не являются отдельными полномочиями. Источник полномочий — запрос пользователя.

F01/F02 воспроизведены на настоящих импорте/SQLite/API. 45см×370мм и450мм×37см
теперь дают450×370 и3976.00 за2 детали с полной кромкой. Явные0/отрицательные/дробные
количества и отрицательная геометрия требуют уточнения, без подтверждаемого quote.
Уточнение отменяет пригодность прежнего черновика; поля корректного ввода сохраняются.
Проверяются полные числовые фрагменты, единицы каждой стороны, именованные оси,
контекст и соответствие model tool quote детерминированно подтверждённым параметрам.

F03 исходно воспроизведён:10.9996→11.000,10 готовых пар,export500.
Единый точный интервал до микросекунд используется в timer/attest/U07 DTO.
Округлённое превышение отклоняется до записи. Legacy ошибочные attestation видны как
требующие проверки, пары не ready, export409 вместо500. Явный reopen требует человека,
причины и актуальной версии; прежние данные/события остаются в append-only истории.

Текущие targeted:36 PASS numeric/labor/report;3 PASS choices+real-C2 wizard.
Это синтетические boundary проверки; настоящих человеческих трудозамеров не добавлялось.

E01: новый мастер выбирает реальные проверенные планы/принятые snapshots на одинаковых
входах/складе/locks, реальные версии протоколов и явные допущения. Общая формула экономики
не меняется. Сценарии выбираются по имени/дате, отрицательный эффект/payback null сохраняются.
E02: типизированные кнопки KB-product/unit/sides связаны с conversation/turn/KB, stale409;
нет автоматического confirm/reserve. E03: read-only ZIP checker сверяет реальные CSV,
исходники/assets, PDF/evidence/результаты с принятым run, сообщает missing/mismatch.
Внешняя приёмка и официальный closed набор остаются отдельными, не присваиваются автоматически.
R01: scripts/build_reports.py --only examples не вызывает economics; synthetic guards сохранены.

Следующий шаг: расширить негативные регрессии/real browser, полный frozen source check;
актуальная baseline/extended серия на одинаковых исходных bytes и конфигурации; настоящие
examples PDF с visual review; обновлённый EXE/релокация, required checks и обычный main push.
Live provider нестабилен, ключ предоставлен ранее; paid не включён. Human10pairs/чистая
Windows11/HTTPS gateway и финальная подача остаются внешними условиями, не PASS.

## Повторная проверка интерфейса

Новые четыре настоящих browser E2E прошли на production UI и отдельной SQLite/TCP:
mixed units3976 → invalid followup без quote; unit-button после refresh с доступным
подтверждением; quantity3 после выбора целого листа510000; мастер экономики и
сохранение/повторное открытие сценария/PDF без JSON/ввода ID.
Трудозамеры последнего теста явно SYNTHETIC, не являются человеческой приёмкой.
Они остаются в отдельной тестовой базе, в финальные материалы не идут.

Browser нашёл и помог исправить два сопутствующих дефекта: перенос product_id/
геометрии/processing из ответа не заполнял каноническую форму, а прежний quoteId
восстанавливал отменённый черновик после неверного количества. Параметры теперь
согласуются структурно, invalid reply очищает сохранённую ссылку; старые KB/turn
кнопки отклоняются409. Названия auto/per_sheet/per_m2/unit показываются по-русски.
Три листа и именные оси дополнительно проверены; price-basis choice сохраняет qty3.

Node24:25 Vitest PASS, typecheck/build PASS;59 fixture E2E PASS отдельно46.6с.
Ruff и foundation14immutable inputs PASS. Полный Python и прежние real suites
проверяются до сборки. Независимая запись требований первого сотрудника и human10pairs:
docs/release/TEAMMATE_ACCEPTANCE_RU.md, включается в новый portable ZIP.


EXE50f54c9:20 browser PASS, changed-input TCP protocol PASS70.625с,
smoke backup/restore+scanner PASS. Local regression147/149,QA10/10,0 provider calls.
Разобраны2 остаточных случая: explicit qty без геометрии теперь спрашивает длину/ширину;
глагол «устанавливаете» использует существующее правило KB. Добавлены4 варианта
регрессий; все intelligence tests PASS с3прежними SKIP. Это исправление по уже
раскрытому oracle, новый независимый экзамен не заявляется.

Первая полная проверка710PASS/3FAIL/4SKIP затронула accepted-row fingerprint: assets
пересобирались во время прогона. DB jobs показывают INVALID_ACCEPTED_ROW;9 checkpoint
тестов на неизменной версии повторно PASS. Полная проверка повторяется после
окончательной фиксации runtime/production assets; fingerprint guards не изменены.


Frozen-source59c1777: полный Python717PASS/4SKIP422.09с. Все20 EXE browser
повторно PASS; native changed-input/export/restart68.453с PASS; backup/restore/scanner
PASS; local149/149 иQA10/10, исключительно deterministic0provider calls.
Live в3 отдельных профилях: luna503,GLM15s timeouts,terra503.0 model answers/15fallback,
8 provider calls; консервативная quota debit142212, usage фактических error calls
неизвестен; все3 закрытые базы/файлы проверены на отсутствие ключа. Paidfalse.

Дополнительно воспроизведён spaced-minus: «− 2 штуки»/«− 450×370» теряли знак.
Полный signed span теперь включает пробелы; цифровые количества перед названием
фурнитуры используют тот же grammar и не превращают denominator/суффикс группы в
количество. Типографское тире-разделитель сохранено отдельной регрессией. Добавлены
8 негативных вариантов; quote отсутствует, требуется quantity/geometry clarification.
Далее: commit финального runtime, EXE и browser/локальный экзамен повторно;
согласованная baseline/extended600 серия, настоящий examples PDF и готовность ZIP.


Отдельный API /quotes/dimensions/normalize дополнительно проверен для всех7
эквивалентных записей: добавлен source_unit=mixed в Python DTO и стандартно
перегенерированы OpenAPI/TS. Финальные49numeric/choices/model/labor regressions PASS,
включая нормализатор; typecheck/build и Ruff PASS. Runtime замораживается для
окончательной EXE/600s серии. 59c1777 CI Linux+Windows PASS; source после него
менялся только в signed numeric grammar/контракте нормализации, проверяется заново.


## Рабочая версия после независимого аудита — итог

База main c6b4b02 сохранена; source commits50f54c9→59c1777→fd1b517→
a0afb4b39cb185a3f13aed570b4b89c2b73e7dff. Автор Mustiks07, существующая git identity.
Runtime digest7e981d206ea2fc63d72e44d68909ea7cd58e27f4f2beb349d421c11541a119cf.
153 tracked Git source/dependency blobs и156 runtime/assets hashes совпали.

Команды: uv sync --locked --all-groups; uv run pytest; uv run ruff check backend tests scripts;
uv run python scripts/check_foundation.py; export_openapi.py; pnpm contracts:generate;
pnpm typecheck/test/build; Playwright audit/real/integrated/post/portable/release configs;
uv run pyinstaller --noconfirm packaging/GlassFlow.spec; smoke_frozen.py; scan_release.py;
post_frozen_acceptance.py; audit_final_series.py (quick5/1 иextended600/7,seed42,minfree5);
prepare_audit_examples.py; build_reports.py --only examples; pdftoppm(all6pages);
audit_open_bundle.py; package_working_build.py. Все версии output сохранены отдельно.

Полный локальный Python725PASS/4SKIP406.20с,25 Vitest/59 fixture отдельно PASS,
22 настоящих EXE browser scenarios PASS. Native changed-input/partial/cancel/deadline/
restart63.609с PASS; backup/restore и запуск именно конечной папки PASS.
Runtime CI Linux+Windows PASS46148987983; окончательный main с документацией получает отдельный CI.

Согласованная серия на тех же7original bytes:55.8080067→59.1256891%,165→201/298
деталей,28→42/110 целых заказов,960645.25→1020157.25₸ оценки материала.
Оба official validate.py invalid=missing0. Это59512₸ замещения на набор, не прибыль.
Первый полный принятый комплект extended10.407с, улучшение принято617.5с.
Первый observer attempt прерван логированиемkind; сохранён как failed, не результат сравнения.
V2 не меняет заранее объявленных входов/конфигурации.

Настоящий examples.pdf:6 просмотренных страниц,3cutting/3answers/3local reminders/3QA;
выпущен отдельно от economics. Readiness реальногоZIP:source/CSV/examples ready,
economics missing; изменённыйCSV mismatch; contest_acceptedfalse.
Прежняя презентация6страниц со placeholders просмотрена/сохранена побайтно, не финальная.

Конечная папка/ZIP Genezis/dist/GlassFlow-audit-a0afb4b;ZIP151700045bytes,
SHA256 f49b085fa0fb75e00652a416203b0fe8e336a15a1932d2841b5cc015725f7d76.
EXE4658ab7957f9d9846d08a56c887ca8bb613c6ec2520e46f778c5c16db4ac218b.
Внутри7byte-exact учебных источников и протокол ноутбука/измерений. CRC/scanner PASS.

Live preflight59c1777:0model/15fallback,8provider calls; luna503/GLMtimeouts/terra503.
Conservative debit142212, прежние199311+5000reserve:346523<1млн первого цикла.
Actual usage ошибок неизвестен. RAM-only key persistence проверен на3закрытых базах/файлах;paidfalse.
Local149/149+QA10/10 на a0 — регрессия раскрытого набора, не новый независимый экзамен/неlive.

Доставка рабочей версии: обычный fast-forward/push main без force. Полная конкурсная
приёмка отдельно: стабильныйlive/tools; новый сотрудник на чистом эталонном ноутбуке;
10реальных пар/стоимостьчаса/объём/расходы и финальныйeconomics; HTTPSgateway;
согласованная презентация/видео/репетиция; официальныеclosedinputs/KEY/подача/гостевойдоступ.
Ноутбуки сокомандников доступны; наблюдение не выполнено. Следующий шаг — эти внешние
проверки по TEAMMATE_ACCEPTANCE_RU.md. Большой редизайн/ночные research upgrades не включены.
Подробные SHA/команды/raw reports: docs/release/audit/README.md и FINAL_STATUS.json.


## Дополнительная граница после публикации a79f69e

Подтверждены1 / 2штуки→2,1 , 5штуки→5,2 3штуки→3. Это тот же дефект
потери полного числового фрагмента. Общий quantity_value теперь сначала проверяет
полный NUMBER grammar, затем удаляет только допустимые разделители тысяч.
Regex охватывает операторы/пробелы/скобки; неподдержанное выражение не даёт
допустимый суффикс. Единый parser используется перед единицей и перед названием
фурнитуры. Добавлено7 регрессий,51 targeted PASS. ENGINE_VERSIONv5 исключаетстарыйcache.
Готовится новый согласованный runtime/EXE/серия; a0/a79 сохраняются как предыдущий
checkpoint. Публикация a79 не объявляется итогом этой дополнительной проверки.

Дополнительный контрольa7d3666 дал148/149:строгийNUMBER отклонил обычную
пунктуацию«количество2.». Исправлены один конечный разделитель предложения/
клаузы и одна сбалансированная пара скобок без удаления внутренних операторов.
После единицы поддержана запятая без пробела:«мм,2шт»не становится1.
Added4positive regressions;55targetedPASS,source HTTP149/149+QA10/10.
ENGINEv6. Все interim proof сохранены; a7d не принят итоговым runtime.

Coref156708:full736PASS/4SKIP419.29с. После его завершения пересобранUI:
служебныеinvalid/assumedflags не показываются как подтверждённые параметры,
selected sides подписаны по-русски.25Vitest/typecheckPASS. Backendпослеfullне меняется.
Новыйbrowserloop ждёткаждыйAPIresponse+historyturn и проверяет quoteNone,
а не староеDOMсостояние. Финальныйruntime включаеттолькоэтотdisplay/testchange
поверхпроверенногоcore; native/fingerprint regressionиCIповторяются.

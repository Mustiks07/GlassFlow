# Статус GPT_PRO_INTEGRATOR

Обновлено: 28 ноября 2026, Asia/Qyzylorda. Команда Vtiposhniki.

## База и история

Работа в отдельном worktree GlassFlow-integration, ветка codex/integration от локального main 2cff2d094754c46434c467f3b79cfe34d3a6e666. Коммиты 24049e1 и 2cff2d0 сохранены предками. Исходный checkout чистый, reset/force не применялись.
Fetch подтвердил: Pro 9f5b9dd92c01c016a9ac44cdf457bbcf277b7114; C2 589747291ce6d4f0db0c55f2088b8341d4121534; C3 0621153; C1 877c122. Foundation 16d63c6. Автор/коммиттер новых commits Mustiks07 <232028042+Mustiks07@users.noreply.github.com>.
Merge Pro 4396799, C2 13922cb, C3 b906992, C1 (см. git log). Авторская история сохранена. README конфликт совмещен по смыслу, generated OpenAPI/TS после каждого конфликта регенерированы из Python DTO.

## Текущий checkpoint (работа продолжается)

Реализована production composition: import hook C2, единый Alembic0004_domains, worker handlers cutting/assistant/quality/cards, canonical C3 dataset/KB/settings/CRM/inventory. U01 OrderSource/SubjectSource читают данные в caller transaction. U04 получает canonical joint selection через process worker; атомарный bundle reserve использует C2 reservations. U06 получает явное operator-recorded execution, независимую геометрию и canonical consume; резерв не создает расход.

C3-F5: введены ссылки commercial_references и рендеринг доверенным кодом. Свободный LLM текст больше не подтверждает цену совпадением чисел. Новый prompt version инвалидирует старый кеш. Новые регрессии проверяют перестановки товара/роли/единицы/количества и чужое наличие. Гибридный local deterministic сохранен. Полная live приемка NOT RUN; прежние81,4% не объявлены PASS. Платный режим не включен.

Тестовые harness C2/C3 приведены к Host/session защите Pro: testing=True разрешает testserver, GET health устанавливает cookie. Runtime security не ослаблена. SyntheticOrderSource теперь заполняет реальный customer_id C3 и отдельно проверяет противоречие аттестации; fake provider тесты передают связанные ссылки вместо недоказуемого денежного текста.

## Проверки на этой стадии

- uv sync --locked --all-groups / pnpm install --frozen-lockfile PASS.
- pnpm typecheck и build PASS после схем и исправления выбора solver profile; vitest20 PASS.
- Targeted C2 inventory+C3 API24 PASS; targeted C3-F5/resilience/Pro orders проходят, новые actual integration сценарии пока исправляются.
- Первый real browser прогон: импорт/копия/CRM/аналитика/reminder/склад/backup PASS; T28 выявил legacy sha256 KB alias в UI. Добавлена canonical Dataset.kb_version. Требуется повтор после перезапуска.
- Полный pytest запущен; окончательный результат еще не зафиксирован.

C1 исходные buyer CSV/evidence не заменяются. scripts/convert_buyer_evidence.py создает отдельный evidence.platform.json с source hashes и явными engineering assumptions для3 публично перепроверенных мебельных организаций. Перепроверка50 HTTP источников выполняется отдельно. Факт активности не называется спросом или вероятностью покупки.

## Осталось

Закончить actual HTTP/C2/C3 U01/U04/U06 regressions, подключить формы C1, повторить полный pytest/Ruff/foundation/contracts/frontend и browser. Выполнить один свежий открытый extended run с5 CSV/validator/hashes, собрать и запустить actual EXE, проверить материалы и обновить README, затем fast-forward main и обычный push. Новые функции ночного исследования не начинались.

Внешние условия: ключ/квота бесплатного проекта команды и новая live оценка >=95%, HTTPS hosting judge gateway/отзывной токен и новый компьютер, чистая Windows без dev tools,10 реальных человеческих трудозамеров, финальные экономика/презентация/репетиция, закрытый набор и будущая подача/явка. Отсутствие этих условий не означает PASS. Финальные PDF без настоящих результатов/замеров не создаются.

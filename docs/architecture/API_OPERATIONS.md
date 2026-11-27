# Реестр операций: обязательный объем разработки

В foundation реализованы health/ready; основные предметные маршруты присутствуют как typed 501. Таблица ниже задает также будущие операции, которые нельзя потерять из-за краткой таблицы API в ТЗ. Все строки требуют реального backend behavior, UI и тестов; наличие URL не равно готовности.

| Owner | Маршруты / операция | Ключевой договор |
|---|---|---|
| Pro | GET /health, /ready | readiness реальных сервисов, foundation явно false |
| Pro | POST /imports/preview, /imports/{id}/commit | безопасный ZIP/CSV, schema/encoding, snapshot, не читать KEY в runtime |
| Pro | GET /datasets, /datasets/{id}; POST /datasets/{id}/working-copy | isolated source/workspace/contest, source hashes |
| C2 | GET/POST /remnants; PATCH /remnants/{id}/measurement | dataset, integer mm, expected_version, invalidate зависимых ссылок |
| C2 | POST /remnants/{id}/consume, /remnants/{id}/release | атомарность, idempotency, version check |
| C2 | POST /cutting/candidates, /cutting/solve | scope availability, jobs platform, snapshot version |
| C2 | GET /plans/{id}; POST /plans/{id}/draft | сохранить новую ревизию редактирования, координаты/rotation/locks/exclusions |
| C2 | POST /plans/{id}/validate, /plans/{id}/commit | независимый validator, optimistic version, резерв |
| C2 | POST /plans/compare | same dataset, Δcoverage/value/whole orders, последствия исключения |
| C3 | GET /catalog; POST /quotes; GET /quotes/{id} | versioned KB, Decimal, mapping and clarification |
| C3 | POST /quotes/{id}/revise, /quotes/{id}/confirm | expected revision, stale KB/inventory, reserve через C2 если применимо |
| C3 | POST /assistant/turns; GET /assistant/conversations/{id} | сохранение предметного контекста, citations, tool audit |
| C3 | POST /quality/check, /quality/batch | OK/ERROR/NEEDS_REVIEW, actual evidence, no KEY leakage |
| Pro | POST /crm/rank; GET /crm/applications | 25 application rows, explicit policy/version, deterministic ties |
| Pro | GET/POST /crm/reminders; GET/PATCH /crm/reminders/{id} | correct recipient, source_app_ids, subject type/version, stale recheck |
| Pro | POST /crm/reminders/{id}/confirm, /crm/reminders/{id}/cancel | local state, no outbound messaging, idempotency |
| Pro | GET /analytics/managers | семь метрик M1–M5 и знаменатели; hidden actual returns N/A |
| Pro | GET /buyers; POST /buyers/import | public registry evidence supplied by C1, 50/30Astana/5categories |
| Pro | POST/GET /sale-cards; POST /sale-cards/{id}/recheck | final plan revision, ≥5 original free whole pieces, exact buyer names |
| Pro | POST /runs; GET /runs/{id}; POST /runs/{id}/export | one snapshot + full RunManifest, exact 5 CSV schemas |
| Pro | GET /jobs/{id}; POST /jobs/{id}/cancel | progress/cancel/last_valid_result/interrupted |
| Pro | GET/PATCH /settings; POST /settings/ai/check | safe profile, secrets server-side, budget/paid opt-in; provider behavior C3 |
| Pro | POST /system/backup, /system/restore, /system/shutdown | local owner authorization, SQLite checkpoint, graceful worker lifecycle |

Указанные дополнительные имена — координационный договор для реализации, не требование организаторов. Владелец уточняет DTO/additive routes в handoff; интегратор регенерирует общую схему и проверяет все потребители. HTTP consumers не должны предполагать, что отсутствующая здесь pagination уже реализована.

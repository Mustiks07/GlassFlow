# Подключение judge_gateway

Этот каталог принадлежит Pro и не подменяет engine C3 в `infra/ai-gateway/`.
Engine и его deploy templates отсутствуют в foundation этой ветки. Реального HTTPS endpoint,
hosting account, токена и проверенной квоты здесь нет: P-11 deployment/full-flow **BLOCKED**.

Платформенные точки готовы:

1. `PATCH /api/v1/settings` с локальным `X-GlassFlow-Session`: profile=`judge_gateway`, gateway_url HTTPS,
   provider, закрепленный model_id, mode=`free_only`, paid_enabled=false, monthly_budget_tg=`0`.
   Отзывной judge token передается как api_key; хранится только в памяти процесса, не в SQLite или URL.
2. `Services.ai_check(settings, secret)` подключает C3 adapter. Проверка ограничена timeout;
   ответ API содержит только available/provider/model_id/capabilities/checked_at. Local `/ready` не зависит от сети.
3. `scripts/check_gateway.py --url https://HOST --token-env GLASSFLOW_JUDGE_TOKEN` проверяет только TLS/health.
   Он не выдает health-check за end-to-end AI, срок токена или квоту.

Для интегратора: сначала получить от C3 фактический Dockerfile/entrypoint, порт, health path,
OpenAPI и server-side configuration names. Затем собрать отдельный deployment target из C3 engine,
настроить HTTPS, серверный provider secret, закрепленные модели, expiry/revocation и глобальные/session/IP
бюджеты. Provider key не копировать в Windows bundle. Публичный judge token не считается сильным секретом.

Приемка требует нового компьютера: холодный старт, actual assistant + tools + verifier, expired/revoked token,
429/timeout, free-only отказ от paid fallback, реальный запас запросов включая retries/verifier,
полный маршрут <=5 минут. Результаты и фактическую стоимость записать в `docs/release/`.
Пакетный contest run команды использует direct profile с проверенной квотой, отдельно от judge profile.

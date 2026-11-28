# Подключение judge_gateway

Pro integration target; engine принадлежит C3 в `infra/ai-gateway/`.
При заключительном fetch engine опубликован в C3 `e83c211`, но соседняя ветка не сливалась здесь.
Реальных provider key, HTTPS hosting account, judge token и проверенной квоты нет: live deployment/full-flow BLOCKED.

## Проверенный контракт C3

- Dockerfile: `infra/ai-gateway/Dockerfile`, build context — корень объединенного репозитория.
- Runtime: `PYTHONPATH=infra/ai-gateway uv run python -m judge_gateway serve --host 0.0.0.0 --port 8080`.
- `GET /healthz` — процесс; `GET /readyz` — политика, ключ и активный токен; `POST /v1/turn` — закрепленный AI.
- Server env: GEMINI_API_KEY или OPENROUTER_API_KEY; GATEWAY_PROVIDER; GATEWAY_MODELS; GATEWAY_MODE;
  GATEWAY_TOKENS_FILE; GATEWAY_GLOBAL_REQUESTS_PER_DAY; GATEWAY_PER_SESSION_RPM; GATEWAY_PER_IP_RPM;
  GATEWAY_MAX_CONCURRENCY; GATEWAY_PROMPT_VERSION; GATEWAY_TRUST_FORWARDED_FOR.
- `httpx` теперь явно зафиксирован Pro в группе intelligence, как запросил C3.

## Deployment artifact

`compose.yaml` собирает C3 target после интеграции. Image tag требует reviewed source commit;
model IDs требуется явно задать после реальной проверки аккаунта. Provider key приходит только из host secret store.
Каталог токенов (hash/expiry/quota) монтируется readonly вне checkout. Token issuance/revocation — CLI C3,
выданный raw token не хранить в Git, логах, URL или Windows EXE. Token file должен быть читаем container UID nobody.

Compose публикует только 127.0.0.1:8080 для выбранного TLS proxy/хостинга. Это не публичный HTTPS endpoint.
Default profile free_only, нулевой денежный бюджет, консервативные caps; они не являются подтвержденной квотой провайдера.
Для OpenRouter использовать server variables и allowlist по C3 DEPLOYMENT.md, без молчаливого платного fallback.
C3 Dockerfile содержит `python:3.12-slim`: перед финальной поставкой интегратор должен закрепить проверенный digest базы.
После ротации/отзыва token file пересоздать контейнер/перезапустить C3 процесс и повторить проверку.

```powershell
docker compose -f infra/judge-integration/compose.yaml config --no-interpolate --quiet
```

Фактически: Compose config PASS; Docker CLI 28.5.1 есть, Docker Desktop Linux daemon недоступен
(named pipe dockerDesktopLinuxEngine отсутствует). Build/start контейнера NOT RUN. Hosting/key/quota также отсутствуют.
Evidence: `docs/release/gateway-preflight.json`.

## Приложение жюри

`PATCH /api/v1/settings` с локальным X-GlassFlow-Session: profile=judge_gateway, gateway_url HTTPS,
проверенный model_id, mode=free_only, paid_enabled=false, monthly_budget_tg=0. Judge token — api_key,
только память сессии. `Services.ai_check(settings, secret)` адаптирует к C3 `service.check_ai(AICheckRequest)`;
Pro/C3 profile DTO различаются, требуется явный adapter при сборке, а не передача чужих kwargs.
Ответ API: только available/provider/model_id/capabilities/checked_at. Local readiness от сети не зависит.

`scripts/check_gateway.py --url https://HOST --token-env GLASSFLOW_JUDGE_TOKEN` проверяет TLS и /healthz,
не выдает health за full AI, expiry или квоту. C3 smoke проверяет также /readyz и /v1/turn.
Приемка с нового компьютера: cold start, actual assistant/tools/verifier, expired/revoked token, 429/timeout,
paid refusal в free_only, реальная квота с retries/verifier, полный путь <=5 минут.
Пакетный contest run команды использует direct profile отдельно от judge profile.

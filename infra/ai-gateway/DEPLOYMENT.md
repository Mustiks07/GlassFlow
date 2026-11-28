# judge_gateway — контракт развертывания (для GPT Pro / интегратора)

Владелец engine: Клауд третий (`infra/ai-gateway/**`). Интеграция хостинга, секретов и пакета жюри — GPT Pro. Этот документ — контракт, а не подтверждение, что шлюз развернут: **живое HTTPS-развертывание в этой сессии не выполнялось (нет аккаунта хостинга и ключа провайдера)**.

## Назначение

Профиль `judge_gateway` дает приложению жюри AI без передачи ключа Gemini/OpenRouter в публичную папку. Локальное приложение отправляет только сообщения диалога и `prompt_version`; шлюз сам закрепляет провайдера, `model_id`, системный prompt, схемы инструментов, потолок токенов и политику `free_only`. Инструменты (расчет, склад, CRM) выполняет локальное приложение; ответы шлюза с tool calls проходят локальную валидацию. У шлюза нет БД и доступа к локальным данным.

## Запуск

Зависимости runtime: основной `pyproject.toml` + группа `intelligence` (FastAPI, uvicorn, pydantic, google-genai, httpx — транзитивно из google-genai; Pro: рекомендую явно добавить `httpx` в группу `intelligence`).

```sh
uv sync --locked --no-dev --group intelligence
PYTHONPATH=infra/ai-gateway uv run python -m judge_gateway serve --host 0.0.0.0 --port 8080
```

Шаблон контейнера: `infra/ai-gateway/Dockerfile` (сборка из корня репозитория). TLS завершает хостинг/обратный прокси; сам процесс слушает HTTP внутри платформы. Клиент (`GatewayProvider`) принимает только `https://` (кроме `localhost`/`127.0.0.1` для проверки).

## Переменные окружения (без значений секретов)

| Имя | Назначение | По умолчанию |
|---|---|---|
| `GEMINI_API_KEY` или `OPENROUTER_API_KEY` | ключ провайдера, только в секретах хостинга | — |
| `GATEWAY_PROVIDER` | `gemini` / `openrouter` | `gemini` |
| `GATEWAY_MODELS` | закрепленные model_id через запятую (первый — основной, далее проверенные резервы) | `gemini-3.5-flash-lite,gemini-3.8-flash` (OpenRouter: `nvidia/nemotron-3.5-super-vl:free`) |
| `GATEWAY_MODE` | `free_only` / `paid_enabled` | `free_only` |
| `GATEWAY_GLOBAL_SPEND_USD` | бюджет для `paid_enabled`; при `free_only` игнорируется (0) | `0` |
| `GATEWAY_TOKENS_FILE` | JSON с хешами конкурсных токенов (не сами токены) | — |
| `GATEWAY_GLOBAL_REQUESTS_PER_DAY` | общий дневной лимит | `1500` |
| `GATEWAY_PER_SESSION_RPM`, `GATEWAY_PER_IP_RPM` | лимиты сессии и IP | `10`, `30` |
| `GATEWAY_MAX_CONCURRENCY` | параллельные вызовы провайдера | `4` |
| `GATEWAY_PROMPT_VERSION` | версия prompt; должна совпадать с приложением | из кода |
| `GATEWAY_TRUST_FORWARDED_FOR` | `1` только за доверенным прокси | `0` |

Приложение жюри: `GLASSFLOW_AI_PROVIDER=judge_gateway`, `GLASSFLOW_GATEWAY_URL=https://…`, `GLASSFLOW_GATEWAY_TOKEN` (через хранилище настроек Pro, не в JS/логах/manifest).

## Защита

- Токен: `gfj_…`, хранится как SHA-256 + срок + квота; выдается один раз (`issue-token`), отзывается (`revoke`), сравнение constant-time. Токен в пакете жюри не считается сильным секретом — поэтому действуют все лимиты ниже.
- Лимиты: тело ≤256 КБ, ≤40 сообщений, ≤24 000 символов контекста, ≤6 раундов инструментов на ход, RPM на токен/сессию/IP, квота токена и сессии, общий дневной лимит, параллельность, deadline 40 с.
- `free_only`: платная модель отклоняется до сетевого вызова (`/readyz` = 503, `/v1/turn` = 409 `POLICY_BLOCKED`); в `paid_enabled` без бюджета — 402.
- Клиент не может передать модель, URL, system prompt, tools, потолок токенов (лишние поля → 422; роль `system` запрещена).
- Логи: id токена, хеш сессии и IP, статус, длительность, размер; без текста сообщений и токена.

## Маршруты

- `GET /healthz` — процесс жив.
- `GET /readyz` — 200 только если политика валидна, ключ провайдера задан и есть активный токен; тело без секретов.
- `POST /v1/turn` — `{session_id, prompt_version, purpose, messages[]}` → `{provider, model_id, text, tool_calls[], usage{input/output/thought/cached tokens, cost_usd|null, cost_source}, finish_reason, provider_state, attempts, fallback_used}`. Ошибки: `{code, message_ru, retry_after_s?}` + `Retry-After`.

## Ротация и отзыв

```sh
PYTHONPATH=infra/ai-gateway uv run python -m judge_gateway issue-token --tokens tokens.json --label jury-2026-11-29 --days 3 --max-requests 500
PYTHONPATH=infra/ai-gateway uv run python -m judge_gateway revoke --tokens tokens.json --token-id jt-xxxx
```

Файл токенов обновляется атомарно; процесс перечитывает его при перезапуске (рестарт после ротации). Ключ провайдера ротируется в секретах хостинга + рестарт.

## Smoke и приемка (обязанность интегратора — с нового компьютера)

```sh
PYTHONPATH=infra/ai-gateway uv run python -m judge_gateway smoke --url https://<host> --token <token>
```

Smoke фиксирует HTTPS, холодный старт `/healthz`, `/readyz`, один ход и фактическую модель. `passed=true` требует HTTPS и 200 на всех трех шагах. Локальный прогон в этой сессии (HTTP, без ключа) — `docs/ai/evidence/gateway/local_process_smoke.json`: `/healthz` 200 за 212 мс, `/readyz` 503 (нет ключа), ход 503 `PROVIDER_NOT_CONFIGURED` — честный отказ, а не PASS.

Ожидания по времени (цели, не измерения): холодный старт бесплатного хостинга может занимать десятки секунд — проверить до релиза и, при необходимости, прогреть перед показом; ход AI — цель p95 ≤15 с (TZ §27). Полный маршрут жюри без автора — ≤5 минут (T54), проверяет интегратор.

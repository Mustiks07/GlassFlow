# GlassFlow web foundation

Общий каркас React/TypeScript. Это не готовый продукт: разделы показывают назначение будущих модулей, а статус сервера читается из настоящих `/api/v1/health` и `/api/v1/ready`.

Из корня workspace после установки зависимостей:

```sh
pnpm --filter @glassflow/web dev
pnpm --filter @glassflow/web typecheck
pnpm --filter @glassflow/web test
pnpm --filter @glassflow/web build
```

Vite слушает `127.0.0.1:5173` и проксирует `/api` на `127.0.0.1:8000`. Ключи AI не передаются браузеру. Моки используются только в unit-тестах; runtime-моков нет.

Агент интерфейса развивает этот каталог по своему полному заданию. Локальные типы `api.ts` пока описывают только запуск; предметные DTO нужно получать из общего OpenAPI-контракта репозитория.

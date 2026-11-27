# GlassFlow web

React 19 + TypeScript + Vite. Server state — TanStack Query, local UI state — Zustand, accessible dialogs — Radix, icons — Lucide.
Transport types come from the backend OpenAPI (`packages/contracts/schema.d.ts`); fields/operations not yet published by a module owner are
marked `Additive`/`Proposed*` in `src/api/types.ts` and listed in `docs/status/CLAUDE_1_ILYAS.md`.

## Commands (from the workspace root or `apps/web`)

```sh
pnpm --filter @glassflow/web dev            # real backend via /api proxy → 127.0.0.1:8000
pnpm --filter @glassflow/web dev:fixture    # explicit TEST mode on :5174, purple banner, no backend
pnpm --filter @glassflow/web typecheck
pnpm --filter @glassflow/web test           # vitest: format/units, API client, screens
pnpm --filter @glassflow/web build
pnpm --filter @glassflow/web check:bundle   # fails if fixture code or key patterns are in dist/
pnpm --filter @glassflow/web e2e:fixture    # Playwright on the fixture build (separate result)
pnpm --filter @glassflow/web e2e:real       # Playwright against a running real backend (separate result)
```

## Honesty rules in code

- `src/api/client.ts` is the only API client: dataset_id on every domain call, in-memory session token (`X-GlassFlow-Session`),
  `Idempotency-Key` kept for the whole user action, `X-Request-ID`, correlation id surfaced in errors, Russian field errors,
  409/422/429/503/501 mapped to distinct states. Forms keep their input after errors.
- The fixture transport (`src/api/fixtures`) is selected only by `VITE_GLASSFLOW_TRANSPORT=fixture` or explicitly in tests.
  There is no fallback from HTTP to fixtures; a normal build does not contain it (`check:bundle`).
- Money is formatted from decimal strings only; the browser never computes a commercial total. Geometry previews in SVG are hints;
  the server validator decides.

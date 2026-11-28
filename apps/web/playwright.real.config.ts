import { defineConfig, devices } from '@playwright/test';

/**
 * Real-backend E2E. Requires a running GlassFlow backend and UI, e.g.
 *   uv run uvicorn glassflow.main:app --port 8000   (repo root, integrated branch)
 *   pnpm --filter @glassflow/web dev               (proxy /api → 8000)
 * GLASSFLOW_E2E_URL overrides the UI address (default http://127.0.0.1:5173; use :8000 for the
 * backend-served production build). Each run starts from a fresh backend data dir.
 */
export default defineConfig({
  testDir: '../../tests/e2e/real',
  outputDir: '../../tests/e2e/.results/real',
  reporter: [['list'], ['json', { outputFile: '../../tests/e2e/.results/real-report.json' }]],
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  use: { baseURL: process.env.GLASSFLOW_E2E_URL ?? 'http://127.0.0.1:5173', trace: 'off', screenshot: 'only-on-failure', locale: 'ru-RU', timezoneId: 'Asia/Qyzylorda' },
  projects: [{ name: 'real-1366', use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 768 } } }],
});

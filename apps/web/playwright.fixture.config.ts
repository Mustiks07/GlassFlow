import { defineConfig, devices } from '@playwright/test';

/**
 * Fixture E2E: the UI built with VITE_GLASSFLOW_TRANSPORT=fixture (purple TEST banner).
 * Proves UI behaviour and states only — NOT backend integration. Results are reported
 * separately from `e2e:real`.
 */
const port = 4174;
export default defineConfig({
  testDir: '../../tests/e2e/fixture',
  outputDir: '../../tests/e2e/.results/fixture',
  reporter: [['list'], ['json', { outputFile: '../../tests/e2e/.results/fixture-report.json' }]],
  timeout: 45_000,
  expect: { timeout: 8_000 },
  fullyParallel: true,
  use: { baseURL: `http://127.0.0.1:${port}`, trace: 'off', screenshot: 'only-on-failure', locale: 'ru-RU', timezoneId: 'Asia/Qyzylorda' },
  projects: [
    { name: 'laptop-1366', use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 768 } } },
    { name: 'full-hd-1920', use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } }, grep: /@visual/ },
    // Browser zoom 125 % on a 1366×768 screen ≈ CSS viewport 1093×614 at DPR 1.25.
    { name: 'zoom-125', use: { ...devices['Desktop Chrome'], viewport: { width: 1093, height: 614 }, deviceScaleFactor: 1.25 }, grep: /@visual|@a11y/ },
  ],
  webServer: {
    command: `pnpm build:fixture && pnpm exec vite preview --outDir dist-fixture --port ${port} --strictPort --host 127.0.0.1`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});

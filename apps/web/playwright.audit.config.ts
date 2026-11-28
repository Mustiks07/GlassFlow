import { defineConfig } from '@playwright/test';
import real from './playwright.real.config';
export default defineConfig({ ...real, testMatch: 'audit-fixes.spec.ts', timeout: 120_000,
  outputDir: '../../tests/e2e/.results/audit', reporter: [['list'], ['json', { outputFile: '../../tests/e2e/.results/audit-report.json' }]],
});

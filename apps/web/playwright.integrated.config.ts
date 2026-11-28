import { defineConfig } from '@playwright/test';
import real from './playwright.real.config';

export default defineConfig({
  ...real,
  testMatch: 'integrated-workflows.spec.ts',
  outputDir: '../../tests/e2e/.results/integrated',
  reporter: [['list'], ['json', { outputFile: '../../tests/e2e/.results/integrated-report.json' }]],
});

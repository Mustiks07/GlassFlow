import { defineConfig } from '@playwright/test';
import real from './playwright.real.config';
export default defineConfig({ ...real, testMatch: 'portable-build.spec.ts',
  outputDir: '../../tests/e2e/.results/portable',
  reporter: [['list'], ['json', { outputFile: '../../tests/e2e/.results/portable-report.json' }]],
});

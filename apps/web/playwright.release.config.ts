import { defineConfig } from '@playwright/test';
import real from './playwright.real.config';
export default defineConfig({ ...real, testMatch: 'release-readiness.spec.ts',
  outputDir: '../../tests/e2e/.results/release-readiness',
  reporter: [['list'], ['json', { outputFile: '../../tests/e2e/.results/release-readiness-report.json' }]],
});

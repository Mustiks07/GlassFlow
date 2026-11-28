import { defineConfig } from '@playwright/test';
import real from './playwright.real.config';

export default defineConfig({ ...real, testMatch: 'post-integration.spec.ts',
  outputDir: '../../tests/e2e/.results/post',
  reporter: [['list'], ['json', { outputFile: '../../tests/e2e/.results/post-report.json' }]],
});

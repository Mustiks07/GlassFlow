import { test, expect } from '@playwright/test';
import path from 'node:path';

test('actual accepted files and PDF pass; missing economics and changed CSV stay visible', async ({ page }) => {
  const dataset = process.env.GLASSFLOW_AUDIT_DATASET;
  const run = process.env.GLASSFLOW_AUDIT_RUN;
  const zip = process.env.GLASSFLOW_AUDIT_ZIP;
  const changed = process.env.GLASSFLOW_AUDIT_CHANGED_ZIP;
  expect(dataset && run && zip && changed, 'Use actual saved series and its archives').toBeTruthy();
  // Restore only UI navigation state for an actual existing run. No API intercepts or domain fixtures.
  await page.addInitScript(({ dataset, run }) => localStorage.setItem('glassflow-ui-v1', JSON.stringify({
    state: { datasetId: dataset, lastRunIds: { [dataset!]: run }, quoteDrafts: {}, reminderDrafts: {}, activePlanIds: {} }, version: 1,
  })), { dataset, run });
  await page.goto('/#/runs');
  await page.getByText('Проверить готовность конкурсного комплекта', { exact: true }).click();
  const input = page.getByLabel('Архив конкурсного комплекта');
  await input.setInputFiles(zip!);
  await page.getByRole('button', { name: 'Проверить файлы, числа и версии' }).click();
  await expect(page.getByText('Исходный код: Готово', { exact: true })).toBeVisible();
  await expect(page.getByText('CSV и версии прогона: Готово', { exact: true })).toBeVisible();
  await expect(page.getByText('Примеры PDF: Готово', { exact: true })).toBeVisible();
  await expect(page.getByText('Экономика PDF: Не хватает', { exact: true })).toBeVisible();
  await expect(page.getByText('Комплект требует доработки', { exact: true })).toBeVisible();
  await page.screenshot({ path: path.resolve(__dirname, '../evidence/audit/actual-release-check.png'), fullPage: true });
  await input.setInputFiles(changed!);
  await page.getByRole('button', { name: 'Проверить файлы, числа и версии' }).click();
  await expect(page.getByText('CSV и версии прогона: Не совпадает', { exact: true })).toBeVisible();
});

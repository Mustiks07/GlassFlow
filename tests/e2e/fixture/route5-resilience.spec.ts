import { expect, test } from '@playwright/test';
import { fillClear6, fixture, open, quoteTotal } from '../support';

// Route 5 / T36: AI provider unavailable → free dialog limited, structured calculation still works locally.
test('T36: AI offline keeps the local calculation and labels the dialog as limited', async ({ page }) => {
  await open(page, 'workplace');
  await fixture(page, c => c.setAiOffline(true));
  await page.getByLabel('Текст запроса').fill('стекло 6 мм 450×370');
  await page.getByRole('button', { name: 'Отправить ассистенту' }).click();
  await expect(page.getByText('Свободный диалог ограничен')).toBeVisible();
  await expect(page.getByText('Локальный режим').first()).toBeVisible();
  await fillClear6(page, '450', '370');
  await page.getByRole('button', { name: 'Рассчитать' }).click();
  await expect.poll(() => quoteTotal(page)).toBe('1 988,00 ₸');
});

test('network loss shows "no connection" with retry; nothing is fabricated', async ({ page }) => {
  await open(page, 'managers');
  await expect(page.getByText('Число заявок')).toBeVisible();
  await fixture(page, c => c.setOffline(true));
  await page.getByRole('button', { name: 'Применить' }).click();
  await page.locator('form.filters select').first().selectOption('M2');
  await page.getByRole('button', { name: 'Применить' }).click();
  await expect(page.getByText(/Нет связи/).first()).toBeVisible({ timeout: 15_000 });
  await fixture(page, c => c.setOffline(false));
  await page.getByRole('button', { name: 'Повторить' }).first().click();
  await expect(page.getByRole('rowheader', { name: 'M2' })).toBeVisible();
});

test('429 shows the rate limit with a retry hint and keeps the input', async ({ page }) => {
  await open(page, 'workplace');
  await fixture(page, c => c.failNext('/assistant/turns', 429, 'RATE_LIMITED'));
  await page.getByLabel('Текст запроса').fill('сколько стоит зеркало');
  await page.getByRole('button', { name: 'Отправить ассистенту' }).click();
  await expect(page.getByText('Свободный диалог ограничен')).toBeVisible();
  await expect(page.getByLabel('Текст запроса')).toHaveValue('сколько стоит зеркало');
});

test('undelivered backend operation is shown as "not connected", not as data', async ({ page }) => {
  await open(page, 'settings/system');
  await expect(page.getByText(/Модуль не подключен/).first()).toBeVisible();
  await expect(page.getByText(/Операция еще не опубликована/).first()).toBeVisible();
});

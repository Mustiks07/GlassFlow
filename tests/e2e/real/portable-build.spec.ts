import { expect, test } from '@playwright/test';
import path from 'node:path';

test('delivered EXE imports its supplied ZIP through the UI and calculates mixed units', async ({ page }) => {
  expect(process.env.GLASSFLOW_STARTER_ZIP, 'Use the delivered study ZIP').toBeTruthy();
  await page.goto('/#/settings/data');
  await page.locator('input[type=file]').setInputFiles(process.env.GLASSFLOW_STARTER_ZIP!);
  await page.getByRole('button', { name: 'Проверить файлы' }).click();
  await expect(page.getByText('Ошибок не найдено')).toBeVisible();
  await page.getByLabel('Название снимка').fill('Проверка поставляемого учебного ZIP');
  await page.getByRole('button', { name: /Создать снимок/ }).click();
  await expect(page.getByText(/Снимок создан/)).toBeVisible();
  await page.getByRole('button', { name: 'Копия', exact: true }).first().click();
  await page.getByRole('dialog').getByRole('button', { name: 'Создать рабочую копию' }).click();
  await page.goto('/#/workplace');
  const input = page.getByLabel('Текст запроса', { exact: true });
  await input.fill('Стекло 6 мм прозрачное 450 мм x 37 см, 2 штуки, евро-кромка по всем сторонам');
  await input.press('Control+Enter');
  await expect(page.locator('.quote-total strong')).toHaveText('3 976,00 ₸');
  await expect(page.getByRole('button', { name: /Подтвердить предложение \(рев/ })).toBeEnabled();
  await page.screenshot({ path: path.resolve(__dirname, '../evidence/audit/portable-starter.png'), fullPage: true });
});

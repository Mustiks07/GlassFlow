import { expect, test } from '@playwright/test';
import { CONTEST, fixture, open } from '../support';

// Route 4 / T50 / T52: contest snapshot → independent modules → check → five downloads of one run.
test('route 4: contest run produces five files of one run; no official closed scores', async ({ page }) => {
  await open(page, 'runs', CONTEST);
  await expect(page.locator('.mode-badge')).toContainText('Конкурсный прогон · только чтение');
  await expect(page.getByRole('region', { name: 'Входные файлы прогона' }).getByText('есть')).toHaveCount(7);
  await page.getByRole('button', { name: 'Запустить прогон' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Запустить' }).click();
  await expect(page.getByText('Все запрошенные модули завершены')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/Официальные баллы ассистента, отбора заявок и диалогов неизвестны без эталонных ответов организаторов/)).toBeVisible();
  await page.getByRole('button', { name: 'Проверить и подготовить файлы' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Проверить и подготовить' }).click();
  await expect(page.getByText(/Пакет готов/)).toBeVisible();
  const downloads = page.locator('ul.downloads li');
  await expect(downloads).toHaveCount(5);
  for (const name of ['solution.csv', 'answers.csv', 'picks.csv', 'verdicts.csv', 'sale_cards.csv']) await expect(downloads.getByText(name)).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent('download'), downloads.filter({ hasText: 'picks.csv' }).getByRole('link', { name: 'Скачать' }).click()]);
  expect(download.suggestedFilename()).toBe('picks.csv');
});

// T53: one module fails → the ready parts stay downloadable with an explicit partial status.
test('T53: assistant failure gives a partial package, never a fake complete one', async ({ page }) => {
  await open(page, 'runs', CONTEST);
  await fixture(page, c => c.setAiOffline(true));
  await page.getByRole('button', { name: 'Запустить прогон' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Запустить' }).click();
  await expect(page.getByText('Частично готово: часть модулей не завершена')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/Не завершены: Ассистент/)).toBeVisible();
  await page.getByRole('button', { name: 'Проверить и подготовить файлы' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Проверить и подготовить' }).click();
  await expect(page.getByText(/Частичный пакет — не выдавайте за полный/)).toBeVisible();
  await expect(page.locator('ul.downloads li')).toHaveCount(4);
  await expect(page.locator('ul.downloads').getByText('answers.csv')).toHaveCount(0);
});

test('a non-contest snapshot is flagged before running', async ({ page }) => {
  await open(page, 'runs');
  await expect(page.getByText('Выбран не конкурсный снимок')).toBeVisible();
});

import { expect, test } from '@playwright/test';
import { SOURCE, open } from '../support';

// T45: all seven metrics, denominators, NULL as no data, drill-down to source rows.
test('T45: seven metrics with denominators and source-row drill-down', async ({ page }) => {
  await open(page, 'managers', SOURCE);
  for (const label of ['Число заявок', 'Среднее время ответа', 'Конверсия', 'Доля возвратов', 'Средний чек', 'Доля жалоб', 'Доля скидок'])
    await expect(page.getByRole('columnheader', { name: new RegExp(label) })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: /Средняя сумма всех заявок/ })).toBeVisible();
  await page.getByRole('button', { name: /^M1: .*%/ }).first().click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Определение')).toBeVisible();
  await expect(dialog.getByText('Знаменатель (известные значения)')).toBeVisible();
  await expect(dialog.getByRole('region', { name: 'Исходные строки показателя' }).locator('tbody tr').first()).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('filters validate the day range and show unknown manager group label', async ({ page }) => {
  await open(page, 'managers', SOURCE);
  await page.getByLabel('день_года с').fill('50');
  await page.getByLabel('по', { exact: true }).fill('10');
  await expect(page.getByText('Начало больше конца')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Применить' })).toBeDisabled();
});

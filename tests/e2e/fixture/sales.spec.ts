import { expect, test } from '@playwright/test';
import { open } from '../support';

// T48 / T49: five cards from free original remnants; committing a new plan makes them stale and blocks export.
test('T48: cards → plan change → stale, export blocked', async ({ page }) => {
  await open(page, 'sales');
  await page.getByRole('button', { name: 'Сгенерировать 5 карточек' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Сгенерировать' }).click();
  await expect(page.locator('article.sale-card')).toHaveCount(5);
  await expect(page.getByText('Экспорт разрешен')).toBeVisible();
  await expect(page.locator('article.sale-card').first().locator('ol.buyers li')).toHaveCount(3);

  await page.goto('/#/cutting');
  await page.getByRole('button', { name: 'Запустить расчет' }).click();
  await expect(page.getByText('Сравнение версий')).toBeVisible({ timeout: 20_000 });
  await page.getByRole('button', { name: 'Открыть новую версию' }).click();
  await page.getByRole('button', { name: /Подтвердить ревизию/ }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Подтвердить план' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);

  await page.goto('/#/sales');
  await expect(page.getByText(/Экспорт заблокирован/)).toBeVisible();
  await expect(page.getByText('Устарела — экспорт заблокирован').first()).toBeVisible();
});

test('T49: card coefficient outside 0.30–0.70 is rejected before sending', async ({ page }) => {
  await open(page, 'sales');
  await page.getByLabel('Коэффициент', { exact: true }).fill('0.75');
  await expect(page.getByText('Коэффициент от 0,30 до 0,70 (например 0,50)').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Сгенерировать 5 карточек' })).toBeDisabled();
});

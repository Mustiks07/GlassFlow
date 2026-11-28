import { expect, test } from '@playwright/test';
import { open } from '../support';

// T22: invalid placement shows a reason, the server rejects it, the active plan stays, the draft is fixable.
test('T22: invalid edit → visible reason → server invalid → active plan unchanged → fix', async ({ page }) => {
  await open(page, 'cutting');
  await expect(page.getByText('Покрытие площади')).toBeVisible();
  await page.getByRole('button', { name: 'Открыть схему R007' }).click();
  const svg = page.getByRole('img', { name: /Остаток R007/ });
  await expect(svg).toBeVisible();
  const table = page.getByRole('region', { name: 'Размещения на R007' });
  await table.getByLabel('x для P0002').fill('2');
  await table.getByLabel('x для P0002').press('Enter');
  await expect(table.getByText(/ближе 5 мм к краю остатка/)).toBeVisible();
  await expect(page.getByText(/Черновик/).first()).toBeVisible();
  await page.getByRole('button', { name: 'Сохранить и проверить' }).click();
  await expect(page.getByText('Сервер: черновик недопустим — активный план не изменен')).toBeVisible();
  // The editor continues on the invalid draft revision; the committed plan is still the active one.
  const versions = page.getByRole('combobox', { name: 'Версия плана' });
  await expect(versions).toContainText('рев. 2 · Недопустим');
  await expect(versions.locator('option', { hasText: 'PLAN-1 · рев. 1 · Подтвержден' })).toHaveCount(1);
  await expect(table.getByText('сервер: недопустимо')).toBeVisible();
  await table.getByLabel('x для P0002').fill('5');
  await table.getByLabel('x для P0002').press('Enter');
  await page.getByRole('button', { name: 'Сохранить и проверить' }).click();
  await expect(page.getByText('Сервер: черновик допустим')).toBeVisible();
  await expect(page.getByRole('button', { name: /Подтвердить ревизию/ })).toBeVisible();
});

test('keyboard editing: arrows move the selected part, R rotates, table reflects coordinates', async ({ page }) => {
  await open(page, 'cutting');
  await page.getByRole('button', { name: 'Открыть схему R007' }).click();
  const table = page.getByRole('region', { name: 'Размещения на R007' });
  await table.getByRole('rowheader', { name: /P0003/ }).click();
  const canvas = page.getByRole('group', { name: /Схема остатка R007/ });
  await canvas.focus();
  await page.keyboard.press('Shift+ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect(table.getByLabel('x для P0003')).toHaveValue('16');
  await page.keyboard.press('r');
  await expect(table.getByLabel('Поворот P0003')).toHaveValue('1');
});

test('tempered remnant is drawn as one whole part without cut lines', async ({ page }) => {
  await open(page, 'cutting');
  await page.getByRole('button', { name: 'Открыть схему R008' }).click();
  await expect(page.getByText('Калёное: деталь целиком, допуск ±2 мм, без резки')).toBeVisible();
  await expect(page.locator('.remnant-svg .svg-edge')).toHaveCount(0);
});

test('solve job shows real stages, last valid plan and comparison; plan not applied automatically', async ({ page }) => {
  await open(page, 'cutting');
  await page.getByRole('button', { name: 'Запустить расчет' }).click();
  await expect(page.getByText('Поиск раскроя')).toBeVisible();
  await expect(page.getByText('Сравнение версий')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/Δ покрытой площади/)).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Версия плана' })).toContainText('PLAN-1');
});

test('NEW parts show distinct reasons; UNKNOWN is not called impossible', async ({ page }) => {
  await open(page, 'cutting');
  await page.getByRole('tab', { name: /Детали заказов/ }).click();
  await page.getByLabel('Состояние').selectOption('new');
  await expect(page.getByText('Премиум-деталь нельзя резать из остатка с дефектом')).toBeVisible();
  await expect(page.getByText('Деталь не помещается в рабочую область остатка с отступом 5 мм')).toBeVisible();
});

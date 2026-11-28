import { expect, test } from '@playwright/test';
import { fillClear6, fixture, open, quoteTotal } from '../support';

// Route 1: request → clarification → exact price → available remnant → explicit confirm → reservation.
test('route 1: free request, clarification, quote, candidate R006, confirm and reserve', async ({ page }) => {
  await open(page, 'workplace');
  await expect(page.getByText(/ТЕСТОВЫЙ РЕЖИМ FIXTURE/)).toBeVisible();
  await page.getByLabel('Текст запроса').fill('Нужно стекло прозрачное 6 мм 450×370, евро-кромка по кругу');
  await page.getByRole('button', { name: 'Отправить ассистенту' }).click();
  await expect(page.getByText('Подтвержденные параметры')).toBeVisible();
  await expect(page.getByText(/Предположения \(не подтверждены\)/)).toBeVisible();
  await page.getByRole('button', { name: 'Перенести в форму расчета' }).click();
  await expect(page.getByLabel('Длина', { exact: true })).toHaveValue('450');
  await fillClear6(page, '45 см', '370');
  await expect(page.getByText('45 см → 450 мм')).toBeVisible();
  await page.getByRole('button', { name: 'Рассчитать' }).click();
  await expect.poll(() => quoteTotal(page)).toBe('1 988,00 ₸');
  await expect(page.getByText('Предварительно, подтверждает менеджер')).toBeVisible();
  await expect(page.getByRole('radio', { name: /R006/ })).toBeChecked();
  await expect(page.getByText(/Стеллаж A, ячейка 6/).first()).toBeVisible();
  await expect(page.locator('figure.scheme svg')).toBeVisible();

  // Showing a candidate does not reserve anything; confirmation is explicit and names the objects.
  await page.getByRole('button', { name: /Подтвердить предложение/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Подтвердить предложение' });
  await expect(dialog.getByText('1 988,00')).toBeVisible();
  await dialog.getByLabel('Кто подтверждает').fill('M2');
  await dialog.getByRole('button', { name: 'Подтвердить предложение' }).click();
  await expect(page.getByText(/Предложение подтверждено \(ревизия 1, M2\)/)).toBeVisible();

  await page.getByRole('button', { name: 'Зарезервировать R006' }).click();
  const reserve = page.getByRole('dialog', { name: 'Зарезервировать R006' });
  await expect(reserve.getByText('Ожидаемая версия')).toBeVisible();
  await reserve.getByRole('button', { name: 'Зарезервировать R006' }).click();
  await expect(page.getByText(/Остаток R006 зарезервирован/)).toBeVisible();
});

// T23/T18: the remnant changes while the manager looks at the answer → server re-check → 409, no silent success.
test('T23: concurrent remnant change before reservation returns a visible conflict', async ({ page }) => {
  await open(page, 'workplace');
  await fillClear6(page, '450', '370');
  await page.getByRole('button', { name: 'Рассчитать' }).click();
  await expect.poll(() => quoteTotal(page)).toBe('1 988,00 ₸');
  await fixture(page, c => c.bumpRemnant('R006'));
  await page.getByRole('button', { name: 'Зарезервировать R006' }).click();
  const reserve = page.getByRole('dialog', { name: 'Зарезервировать R006' });
  await reserve.getByRole('button', { name: 'Зарезервировать R006' }).click();
  await expect(reserve.getByText('Конфликт версий')).toBeVisible();
  await expect(reserve.getByText(/R006/).first()).toBeVisible();
  await expect(reserve.getByText(/Состояние склада обновлено/)).toBeVisible();
  await expect(page.getByText(/зарезервирован \(версия/)).toHaveCount(0);
});

test('form input survives a refresh and an API error', async ({ page }) => {
  await open(page, 'workplace');
  await fillClear6(page, '450', '370');
  await fixture(page, c => c.failNext('/quotes', 503, 'DEPENDENCY_DOWN'));
  await page.getByRole('button', { name: 'Рассчитать' }).click();
  await expect(page.getByText(/Сервис недоступен · Расчет/)).toBeVisible();
  await expect(page.getByLabel('Длина', { exact: true })).toHaveValue('450');
  await page.reload();
  await expect(page.getByLabel('Длина', { exact: true })).toHaveValue('450');
  await expect(page.getByLabel('Ширина', { exact: true })).toHaveValue('370');
});

test('immutable source snapshot cannot be confirmed; working copy is offered', async ({ page }) => {
  await open(page, 'workplace', 'ds-source-fixture');
  await expect(page.locator('.mode-badge')).toContainText('Исходный снимок · только чтение');
  await fillClear6(page, '450', '370');
  await page.getByRole('button', { name: 'Рассчитать' }).click();
  await expect.poll(() => quoteTotal(page)).toBe('1 988,00 ₸');
  await expect(page.getByText(/доступны только в рабочей копии/)).toBeVisible();
  await expect(page.getByRole('button', { name: /Подтвердить предложение/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Рабочая копия' }).first().click();
  await expect(page.getByRole('dialog', { name: 'Создать рабочую копию' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

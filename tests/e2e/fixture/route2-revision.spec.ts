import { expect, test } from '@playwright/test';
import { fillClear6, open, quoteTotal } from '../support';

// Route 2 / T28 / T21: size change → stale old total → new revision with diff → no free remnant at 451.
test('route 2: 450→451 marks the old total stale and creates revision 2 with a diff', async ({ page }) => {
  await open(page, 'workplace');
  await fillClear6(page, '450', '370');
  await page.getByRole('button', { name: 'Рассчитать' }).click();
  await expect.poll(() => quoteTotal(page)).toBe('1 988,00 ₸');
  await page.getByLabel('Длина', { exact: true }).fill('451');
  await expect(page.getByText(/не является новым итогом/).first()).toBeVisible();
  await expect(page.locator('.quote-total strong')).toHaveClass(/strike/);
  await expect(page.getByText(/Кандидаты будут найдены заново после пересчета/)).toBeVisible();
  await page.getByRole('button', { name: /Пересчитать/ }).click();
  await expect.poll(() => quoteTotal(page)).toBe('1 991,76 ₸');
  await expect(page.getByText(/ревизия 2/).first()).toBeVisible();
  const diff = page.getByRole('region', { name: 'Разница ревизий' });
  await expect(diff.getByText('1 988,00 ₸')).toBeVisible();
  await expect(diff.getByText('1 991,76 ₸')).toBeVisible();
  await expect(page.getByText(/Свободного подходящего куска нет/)).toBeVisible();
  await expect(page.getByText(/не доказывает невозможность после общего перепланирования/)).toBeVisible();
});

test('T28: quantity 2 of the original part is 3 976,00', async ({ page }) => {
  await open(page, 'workplace');
  await fillClear6(page, '450', '370', '2');
  await page.getByRole('button', { name: 'Рассчитать' }).click();
  await expect.poll(() => quoteTotal(page)).toBe('3 976,00 ₸');
});

test('T27: unmapped catalog product is not "no stock" and not NEW; no invented total', async ({ page }) => {
  await open(page, 'workplace');
  const product = page.getByLabel(/Товар каталога/);
  await expect(product.locator('option')).not.toHaveCount(1);
  await product.selectOption('steklo-riflenoe-8');
  await page.getByLabel('Длина', { exact: true }).fill('500');
  await page.getByLabel('Ширина', { exact: true }).fill('500');
  await page.getByRole('button', { name: 'Рассчитать' }).click();
  await expect(page.getByText(/это не «нет в наличии» и не NEW/)).toBeVisible();
  await expect.poll(() => quoteTotal(page)).toBe('не определен');
  await expect(page.getByText(/Неизвестные позиции — числа не выдумываются/)).toBeVisible();
  await expect(page.getByText(/170 000/).first()).toBeVisible();
});

test('ambiguous unit input asks for clarification instead of rounding', async ({ page }) => {
  await open(page, 'workplace');
  await fillClear6(page, '45,55 см', '370');
  await page.getByRole('button', { name: 'Рассчитать' }).click();
  await expect(page.getByText('Размер не равен целому числу миллиметров — уточните значение')).toBeVisible();
  await expect(page.locator('.quote-total')).toHaveCount(0);
});

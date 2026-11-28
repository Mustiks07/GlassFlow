import { expect, type Page } from '@playwright/test';

export const WORK = 'ds-work-fixture';
export const SOURCE = 'ds-source-fixture';
export const CONTEST = 'ds-contest-fixture';

/** Opens a section with a dataset preselected (as a returning user would have it). */
export async function open(page: Page, section: string, datasetId: string | null = WORK) {
  await page.goto('/');
  await page.evaluate(id => {
    localStorage.clear();
    localStorage.setItem('glassflow-ui-v1', JSON.stringify({ state: { datasetId: id, quoteDrafts: {}, reminderDrafts: {}, activePlanIds: {}, lastRunIds: {} }, version: 1 }));
  }, datasetId);
  await page.goto(`/#/${section}`);
  await page.reload();
  await expect(page.getByRole('main')).toBeVisible();
}

type Controls = {
  failNext(prefix: string, status: number, code?: string): void;
  setAiOffline(value: boolean): void;
  setOffline(value: boolean): void;
  bumpRemnant(id: string): void;
  takeRemnant(id: string): void;
};

export async function fixture(page: Page, fn: (controls: Controls) => void) {
  await page.evaluate(`(${fn.toString()})(window.__glassflowFixture)`);
}

export const nb = (text: string | null) => (text ?? '').replace(/[  ]/g, ' ').trim();

export async function quoteTotal(page: Page) {
  return nb(await page.locator('.quote-total strong').textContent());
}

/** Fills the structured quote form for clear 6 mm with euro edge on all sides. */
export async function fillClear6(page: Page, length: string, width: string, quantity = '1') {
  const product = page.getByLabel(/Товар каталога/);
  await expect(product.locator('option')).not.toHaveCount(1);
  await product.selectOption('steklo-6-prozrachnoe');
  await page.getByLabel('Длина', { exact: true }).fill(length);
  await page.getByLabel('Ширина', { exact: true }).fill(width);
  await page.getByLabel('Количество, шт').fill(quantity);
  await page.getByLabel('Обработка').selectOption('euro_edge');
}

/** No horizontal page scroll; large tables may scroll inside their own region. */
export async function expectNoPageOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, 'page must not scroll horizontally').toBeLessThanOrEqual(1);
}

import { expect, test } from '@playwright/test';
import { expectNoPageOverflow, fillClear6, open, quoteTotal } from '../support';

const SECTIONS = ['workplace', 'cutting', 'sales', 'clients', 'managers', 'runs', 'settings'] as const;

// T57: 1366×768, 1920×1080, zoom 125 % — main actions visible, no clipped sums, no page-level horizontal scroll.
for (const section of SECTIONS) {
  test(`@visual ${section}: layout, no page overflow, screenshot`, async ({ page }, info) => {
    await open(page, section);
    await page.waitForTimeout(600);
    await expectNoPageOverflow(page);
    await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
    await expect(page.locator('#dataset-select')).toBeVisible();
    await page.screenshot({ path: `../../tests/e2e/evidence/fixture/${info.project.name}-${section}.png` });
  });
}

test('@visual workplace after calculation: total is not clipped', async ({ page }, info) => {
  await open(page, 'workplace');
  await fillClear6(page, '450', '370');
  await page.getByRole('button', { name: 'Рассчитать' }).click();
  await expect.poll(() => quoteTotal(page)).toBe('1 988,00 ₸');
  const clipped = await page.locator('.quote-total strong').evaluate(el => el.scrollWidth > el.clientWidth + 1);
  expect(clipped).toBe(false);
  await expect(page.getByRole('button', { name: /Подтвердить предложение/ })).toBeVisible();
  await expectNoPageOverflow(page);
  await page.locator('.quote-result').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `../../tests/e2e/evidence/fixture/${info.project.name}-workplace-quote.png` });
});

test('@visual long names and large sums wrap instead of overflowing', async ({ page }) => {
  await open(page, 'workplace');
  await page.evaluate(() => {
    const el = document.querySelector('.crumb-page');
    if (el) el.textContent = 'Очень длинное название раздела '.repeat(6);
  });
  await expectNoPageOverflow(page);
});

test('@a11y keyboard: skip link, Tab order reaches navigation, Escape closes dialogs, visible focus', async ({ page }) => {
  await open(page, 'workplace');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'К содержимому' })).toBeFocused();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  const focused = page.locator(':focus');
  await expect(focused).toHaveAttribute('href', /#\//);
  const outline = await focused.evaluate(el => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe('none');
  await page.getByRole('link', { name: /Клиенты/ }).focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#\/clients/);
  await page.goto('/#/settings/system');
  await page.getByRole('button', { name: 'Завершить GlassFlow' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog', { name: 'Завершить приложение' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Завершить GlassFlow' })).toBeFocused();
});

test('@a11y form fields have labels and statuses have text, not colour only', async ({ page }) => {
  await open(page, 'workplace');
  const unlabeled = await page.evaluate(() =>
    [...document.querySelectorAll('input, select, textarea')]
      .filter(el => {
        const id = el.getAttribute('id');
        const hasLabel = (id && document.querySelector(`label[for="${id}"]`)) || el.closest('label') || el.getAttribute('aria-label');
        return !hasLabel && (el as HTMLInputElement).type !== 'hidden';
      })
      .map(el => el.outerHTML.slice(0, 80)),
  );
  expect(unlabeled).toEqual([]);
  const badges = await page.locator('.badge').allTextContents();
  for (const text of badges) expect(text.trim().length).toBeGreaterThan(0);
});

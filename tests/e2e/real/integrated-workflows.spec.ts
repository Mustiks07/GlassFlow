import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';

async function workspace(page: Page, name: string) {
  await page.goto('/#/workplace');
  await page.request.get('/api/v1/session');
  const source = await page.request.post('/api/v1/datasets/demo', { headers: { 'Idempotency-Key': `browser-demo:${name}` } });
  expect(source.ok()).toBeTruthy();
  const d = (await source.json()).dataset_id;
  const response = await page.request.post(`/api/v1/datasets/${d}/working-copy`, { data: { name }, headers: { 'Idempotency-Key': `${name}:${Date.now()}` } });
  expect(response.ok()).toBeTruthy();
  const copy = await response.json();
  await page.reload();
  await page.locator('#dataset-select').selectOption(copy.dataset_id);
  return copy.dataset_id as string;
}

test('actual U01 → warehouse → U06 via the visible production UI', async ({ page }) => {
  await workspace(page, 'E2E actual single order');
  await page.getByLabel(/Товар каталога/).selectOption({ label: 'Стекло 6 мм прозрачное' });
  await page.getByLabel('Длина', { exact: true }).fill('450');
  await page.getByLabel('Ширина', { exact: true }).fill('370');
  await page.getByLabel('Обработка').selectOption('euro_edge');
  await page.getByLabel(/Заказчик текущего предложения/).fill('BROWSER-CUSTOMER');
  await page.getByRole('button', { name: 'Рассчитать', exact: true }).click();
  await expect(page.locator('.quote-total strong')).toContainText('988');
  await page.getByRole('button', { name: /Подтвердить предложение \(рев/ }).click();
  await page.getByRole('dialog').getByLabel('Кто подтверждает').fill('M2');
  await page.getByRole('dialog').getByRole('button', { name: 'Подтвердить предложение', exact: true }).click();
  const flow = page.getByRole('region', { name: 'Предложение и задание складу' });
  await flow.getByRole('button', { name: 'Создать лист из подтвержденного расчета' }).click();
  await flow.getByRole('button', { name: 'Привязать текущий расчет и кусок' }).click();
  await expect(flow.getByText('Задание складу', { exact: true })).toBeVisible();
  await flow.getByRole('button', { name: 'Подтвердить предложение', exact: true }).click();
  await flow.getByRole('button', { name: 'Резерв для заказа', exact: true }).click();
  await flow.getByLabel('Заметка личной проверки').fill('Кусок и место сверены на складе');
  await flow.getByRole('button', { name: 'Склад проверен лично' }).click();
  await flow.getByRole('button', { name: 'Передать в работу', exact: true }).click();
  await flow.getByRole('button', { name: 'Проверить фактическое исполнение' }).click();
  await flow.getByLabel('Результат проверки / причина расхождения').fill('Фактический размер совпадает с заданием');
  await flow.getByRole('checkbox', { name: /Я сверил фактические/ }).check();
  await flow.getByRole('button', { name: 'Подтвердить фактический расход один раз' }).click();
  await expect(flow.getByRole('status')).toHaveText('Фактический расход записан. Повторного списания нет.');
  await expect(flow.getByText('Запись расхода для поддержки').locator('..')).toHaveJSProperty('open', false);
  await page.screenshot({ path: path.resolve(__dirname, '../evidence/real/U01-U06-actual.png') });
});

test('actual U04: several lines, joint reserve and actual use', async ({ page }) => {
  await workspace(page, 'E2E actual basket');
  await page.getByRole('tab', { name: 'Корзина и расход' }).click();
  await page.getByLabel('Заказчик корзины').fill('BROWSER-BASKET');
  await page.getByLabel('Позиции заявки, каждая с новой строки').fill('2 шт стекло 6 мм прозрачное 200×100 мм; 1 шт стекло 6 мм прозрачное 220×120 мм');
  await page.getByRole('button', { name: 'Разобрать все позиции' }).click();
  await expect(page.getByLabel('Товар позиции 1')).toBeVisible();
  await expect(page.getByLabel('Товар позиции 2')).toBeVisible();
  await page.getByLabel('Заметка проверки всех позиций').fill('Проверены обе позиции, количество и размеры');
  await page.getByRole('button', { name: 'Проверил строки — рассчитать и подобрать совместно' }).click();
  const confirm = page.getByRole('button', { name: 'Подтвердить всю корзину' });
  await expect(confirm).toBeEnabled({ timeout: 45_000 });
  await confirm.click();
  await page.getByRole('button', { name: 'Резерв всей корзины', exact: true }).click();
  await page.getByRole('button', { name: 'Все позиции проверены на складе' }).click();
  await page.getByRole('button', { name: 'Передать корзину в работу' }).click();
  await page.getByRole('button', { name: 'Проверить фактическое исполнение' }).click();
  await expect(page.getByLabel('Фактическая длина, мм')).toHaveCount(3);
  await page.getByLabel('Результат проверки / причина расхождения').fill('Все три фактические детали совпадают с заданием');
  await page.getByRole('checkbox', { name: /Я сверил фактические/ }).check();
  await page.getByRole('button', { name: 'Подтвердить фактический расход один раз' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Фактический расход сохранен' })).toHaveText('Фактический расход сохранен. Повторного списания нет.');
  await expect(page.getByText('Запись расхода для поддержки').locator('..')).toHaveJSProperty('open', false);
  for (const [width, height, zoom] of [[1366, 768, 1], [1920, 1080, 1], [1366, 768, 1.25]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(z => { document.body.style.zoom = String(z); }, zoom);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
    await page.screenshot({ path: path.resolve(__dirname, `../evidence/real/U04-${width}-${zoom}.png`) });
  }
});

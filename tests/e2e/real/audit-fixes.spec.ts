import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';

async function post(page: Page, route: string, data?: unknown) {
  const response = await page.request.post('/api/v1' + route, { data, headers: { 'Idempotency-Key': `audit-browser:${Date.now()}:${Math.random()}` } });
  expect(response.ok(), await response.text()).toBeTruthy(); return response.json();
}
async function workspace(page: Page, name: string) {
  await page.goto('/#/workplace'); await page.request.get('/api/v1/session');
  const source = await post(page, '/datasets/demo');
  const copy = await post(page, `/datasets/${source.dataset_id}/working-copy`, { name });
  await page.reload(); await page.locator('#dataset-select').selectOption(copy.dataset_id); return copy;
}

test('mixed units and invalid numbers through the visible assistant', async ({ page }) => {
  await workspace(page, 'Audit numerical browser checks');
  const normalized = await page.request.post('/api/v1/quotes/dimensions/normalize', { data: { text: '45 см x 370 мм' } });
  expect(normalized.ok(), await normalized.text()).toBeTruthy();
  expect(await normalized.json()).toMatchObject({ source_unit: 'mixed', dimensions: { length_mm: 450, width_mm: 370 } });
  const input = page.getByLabel('Текст запроса', { exact: true });
  await input.fill('Стекло 6 мм прозрачное 45 см x 370 мм, 2 штуки, евро-кромка по всем сторонам');
  await input.press('Control+Enter');
  await expect(page.locator('.quote-total strong')).toHaveText('3 976,00 ₸');
  for (const invalid of ['-2', '− 2', '0', '1,5', '1 / 2', '2 3', '(-2)']) {
    const history = page.getByRole('list', { name: 'История уточнений' }).locator(':scope > li');
    const previous = await history.count();
    await input.fill(`Количество: ${invalid} штуки`);
    await expect(page.getByRole('button', { name: 'Отправить ассистенту', exact: true })).toBeEnabled();
    const response = page.waitForResponse(r => r.url().endsWith('/assistant/turns') && r.request().method() === 'POST');
    await input.press('Control+Enter');
    const reply = await (await response).json();
    expect(reply.quote).toBeNull();
    expect(reply.status).toBe('clarification');
    await expect(history).toHaveCount(previous + 2);
    await expect(page.getByText(/Укажите положительное целое количество вместо/).first()).toBeVisible();
    await expect(page.locator('.quote-total')).toHaveCount(0);
    await expect(page.locator('.confirmed-params .chips')).not.toContainText(['True']);
  }
  await page.screenshot({ path: path.resolve(__dirname, '../evidence/audit/numeric-invalid.png'), fullPage: true });
});

test('clarification button survives refresh and never confirms the quote', async ({ page }) => {
  await workspace(page, 'Audit typed clarification');
  await page.getByLabel('Текст запроса', { exact: true }).fill('Стекло 6 мм прозрачное 45,0x37,0, 2 штуки, евро-кромка по всем сторонам');
  await page.getByLabel('Текст запроса', { exact: true }).press('Control+Enter');
  await expect(page.getByRole('button', { name: 'Сантиметры', exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Сантиметры', exact: true }).click();
  await expect(page.locator('.quote-total strong')).toHaveText('3 976,00 ₸');
  await expect(page.getByRole('button', { name: /Подтвердить предложение \(рев/ })).toBeEnabled();
  await page.screenshot({ path: path.resolve(__dirname, '../evidence/audit/typed-choice.png'), fullPage: true });
});

test('three sheets keep their quantity after the price-basis button', async ({ page }) => {
  await workspace(page, 'Audit sheet quantity');
  const input = page.getByLabel('Текст запроса', { exact: true });
  await input.fill('Сколько стоят три штуки рифлёного прозрачного стекла 8 мм?');
  await input.press('Control+Enter');
  await page.getByRole('button', { name: 'Цена за целый лист', exact: true }).click();
  await expect(page.locator('.quote-total strong')).toHaveText('510 000,00 ₸');
  await expect(page.getByRole('textbox', { name: 'Количество, шт', exact: true })).toHaveValue('3');
});

test('economics wizard selects real plans and synthetic test measurements without JSON or typed IDs', async ({ page }) => {
  const d = await workspace(page, 'SYNTHETIC automated wizard route, NOT human labor evidence');
  const job = await post(page, '/cutting/solve', { dataset_id: d.dataset_id, config: { profile: 'quick', time_limit_seconds: 3 } });
  await expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${job.job_id}`)).json()).state, { timeout: 35_000 }).toBe('completed');
  const plan = (await (await page.request.get(`/api/v1/jobs/${job.job_id}`)).json()).result;
  const placed = plan.placements.find((p: { remnant_id: string }) => p.remnant_id !== 'NEW');
  const draft = await post(page, `/plans/${plan.plan_id}/draft`, { dataset_id: d.dataset_id, base_revision: plan.revision, edits: [{ part_id: placed.part_id, action: 'unplace' }] });
  const validated = await page.request.post(`/api/v1/plans/${plan.plan_id}/validate?dataset_id=${d.dataset_id}&revision=${draft.plan.revision}`); expect(validated.ok()).toBeTruthy();
  // These are explicitly automated software-test intervals. They are never a real economic result.
  let s = await post(page, '/labor-studies', { dataset_id: d.dataset_id, name: 'SYNTHETIC browser data — not real human work', observer: 'automated-browser', protocol: 'Automated regression only', start_definition: 'API start', end_definition: 'API finish' });
  for (let n = 0; n < 10; n++) {
    const order = n % 2 === 0 ? ['manual', 'app'] : ['app', 'manual'];
    for (const method of order) {
      s = await post(page, `/labor-studies/${s.study_id}/measurements`, { dataset_id: d.dataset_id, expected_version: s.version, pair_id: `automated-pair-${n}`, task_id: `automated-task-${n}`, task_input_ref: `test-only:${n}`, input_hash: 'a'.repeat(64), operator: 'automated-browser', method, planned_order: `${order[0]}_first` });
      const id = s.measurements.at(-1).measurement_id;
      s = await post(page, `/labor-studies/${s.study_id}/measurements/${id}/finish`, { dataset_id: d.dataset_id, expected_version: s.version, operator: 'automated-browser', result_ref: `synthetic-result:${n}:${method}` });
      s = await post(page, `/labor-studies/${s.study_id}/measurements/${id}/attest`, { dataset_id: d.dataset_id, expected_version: s.version, operator: 'automated-browser', active_seconds: '0.000001', human_confirmed: true, note: 'SYNTHETIC automated test of the confirmation API; not human evidence' });
    }
  }
  await page.getByRole('tab', { name: 'Экономика', exact: true }).click();
  await expect.poll(() => page.getByLabel('Результат для сравнения', { exact: true }).locator('option').count()).toBeGreaterThanOrEqual(3);
  const options = await page.getByLabel('Результат для сравнения', { exact: true }).locator('option').evaluateAll(nodes => nodes.map(n => ({ value: (n as HTMLOptionElement).value, text: n.textContent })));
  expect(options.length).toBeGreaterThanOrEqual(3);
  await page.getByLabel('Результат для сравнения', { exact: true }).selectOption(options[1].value);
  await page.getByLabel('Итоговый результат', { exact: true }).selectOption({ index: 1 });
  await page.getByLabel('Протокол измерений', { exact: true }).selectOption({ label: `${s.name} · готово 10 пар` });
  for (const [label, value] of [['Операций в месяц', '100'], ['Наборов заказов в месяц', '1'], ['Стоимость часа, ₸', '3600'], ['Доля использования прироста, 0–1', '1'], ['ИИ в месяц, ₸', '0'], ['Хостинг в месяц, ₸', '100'], ['Поддержка в месяц, ₸', '100'], ['Разовое внедрение, ₸', '1000']]) await page.getByLabel(label, { exact: true }).fill(value);
  for (const label of ['Основание стоимости часа', 'Источник месячного объёма', 'Основание расходов на ИИ, хостинг и поддержку', 'Основание стоимости внедрения', 'Основание доли использования материала']) await page.getByLabel(label, { exact: true }).fill('SYNTHETIC browser regression assumption, not measured business evidence');
  await page.getByLabel('Название сценария', { exact: true }).fill('SYNTHETIC browser scenario — NOT contest economics');
  await page.getByRole('button', { name: 'Рассчитать сценарий', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Скачать PDF этой версии' })).toBeVisible();
  await page.reload(); await page.getByRole('tab', { name: 'Экономика', exact: true }).click();
  await page.getByLabel('Сохранённые сценарии', { exact: true }).selectOption({ index: 1 });
  await expect(page.getByRole('link', { name: 'Скачать PDF этой версии' })).toBeVisible();
  await page.screenshot({ path: path.resolve(__dirname, '../evidence/audit/wizard-software-only.png'), fullPage: true });
});

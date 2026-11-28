import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';

async function workspace(page: Page, name: string) {
  await page.goto('/#/workplace');
  await page.request.get('/api/v1/session');
  const original = await page.request.post('/api/v1/datasets/demo', { headers: { 'Idempotency-Key': `post-demo:${name}` } });
  expect(original.ok()).toBeTruthy();
  const d = (await original.json()).dataset_id;
  const response = await page.request.post(`/api/v1/datasets/${d}/working-copy`, { data: { name }, headers: { 'Idempotency-Key': `post:${name}:${Date.now()}` } });
  expect(response.ok()).toBeTruthy();
  const copy = await response.json();
  await page.reload(); await page.locator('#dataset-select').selectOption(copy.dataset_id);
  return copy;
}

test('real comparable groups and backend-calculated Russian question', async ({ page }) => {
  await workspace(page, 'Post comparable groups');
  await page.goto('/#/managers');
  await page.getByText('Сравнить внутри сопоставимых групп', { exact: true }).click();
  await page.getByLabel('Группировка').selectOption('channel');
  await page.getByRole('button', { name: 'Сравнить', exact: true }).click();
  await expect(page.getByText(/700 заявок ·/)).toBeVisible();
  await page.getByLabel('Вопрос по агрегатам').fill('Какой средний чек у M1 и M2 по каналам?');
  await page.getByRole('button', { name: 'Посчитать', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Сравнение по одному показателю' })).toBeVisible();
  await page.screenshot({ path: path.resolve(__dirname, '../evidence/post/N08-actual.png'), fullPage: true });
});

test('old printed label opens current record without authorizing mutation', async ({ page }) => {
  const d = await workspace(page, 'Post physical label');
  const pieces = await page.request.get(`/api/v1/remnants?dataset_id=${d.dataset_id}`);
  const piece = (await pieces.json())[0];
  const response = await page.request.post('/api/v1/piece-labels', { data: { dataset_id: d.dataset_id,
    remnant_id: piece.remnant_id, expected_version: piece.version, operator: 'automated-browser-check' }, headers: { 'Idempotency-Key': `post-label:${Date.now()}` } });
  expect(response.ok()).toBeTruthy(); const label = await response.json();
  const change = await page.request.patch(`/api/v1/remnants/${piece.remnant_id}/measurement`, { data: { dataset_id: d.dataset_id,
    expected_version: piece.version, dimensions: { ...piece.dimensions, length_mm: piece.dimensions.length_mm + 1 }, reason: 'Automated stale label verification' } });
  expect(change.ok()).toBeTruthy();
  await page.goto('/#/cutting');
  await page.getByText('Открыть кусок по старой бирке / QR', { exact: true }).click();
  await page.getByLabel('Содержимое QR или ID бирки').fill(label.scan_payload);
  await page.getByRole('button', { name: 'Открыть актуальную запись' }).click();
  await expect(page.getByText(/текущая версия 1/)).toBeVisible();
  await expect(page.getByText('Бирка не разрешает резерв или списание.', { exact: true })).toBeVisible();
  const current = await page.request.get(`/api/v1/remnants/${piece.remnant_id}?dataset_id=${d.dataset_id}`);
  expect((await current.json()).status).toBe('available');
  await page.screenshot({ path: path.resolve(__dirname, '../evidence/post/N09-stale-label.png'), fullPage: true });
});

test('labor timer records browser operation but does not fabricate human attestation', async ({ page }) => {
  await workspace(page, 'Automated timer test, not human labor');
  await page.getByRole('tab', { name: 'Экономика', exact: true }).click();
  await page.getByText('Новый протокол', { exact: true }).click();
  await page.getByLabel('Наблюдатель', { exact: true }).fill('automated-browser-check');
  await page.getByRole('button', { name: 'Создать протокол', exact: true }).click();
  await page.getByText('Начать ручное или автоматизированное выполнение', { exact: true }).click();
  await page.getByLabel('Оператор', { exact: true }).fill('automated-browser-check');
  await page.getByLabel('Название парного замера', { exact: true }).fill('automated-not-human');
  await page.getByLabel('Название задачи', { exact: true }).fill('timer-ui-only');
  await page.getByLabel('Ссылка на входные данные задачи').fill('test://timer-ui-not-human');
  await page.getByLabel('Одинаковый текст и параметры задачи').fill('Automated timer UI verification. No human active time is attested.');
  await page.getByRole('button', { name: 'Начать измерение', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Пауза', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Пауза', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Продолжить измерение', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Продолжить измерение', exact: true }).click();
  await page.getByLabel(/Ссылка на результат/).fill('test://automated-timer-result');
  await page.getByRole('button', { name: 'Завершить выполнение', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Подтвердить активное время', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Перенести подтверждённые пары в экономику', exact: true })).toBeDisabled();
  await page.screenshot({ path: path.resolve(__dirname, '../evidence/post/N05-unattested-automation.png'), fullPage: true });
});

test('actual correction draft is visible without changing original dialogue', async ({ page }) => {
  await workspace(page, 'Post correction draft');
  await page.getByRole('tab', { name: 'Проверка ответа менеджера' }).click();
  await page.getByRole('textbox', { name: 'Вопрос клиента', exact: true }).fill('Сколько стоит стекло 6 мм прозрачное за м2?');
  await page.getByRole('textbox', { name: 'Ответ менеджера', exact: true }).fill('Стекло 6 мм прозрачное стоит 100 тенге за м2.');
  await page.getByRole('button', { name: 'Проверить ответ', exact: true }).click();
  await page.getByRole('button', { name: 'Подготовить проверенный черновик исправления' }).click();
  await expect(page.getByText('Черновик проверен по действующей базе знаний', { exact: true })).toBeVisible();
  await expect(page.getByText(/История диалога сохранена; автоматической отправки нет/)).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Ответ менеджера', exact: true })).toHaveValue('Стекло 6 мм прозрачное стоит 100 тенге за м2.');
  await page.screenshot({ path: path.resolve(__dirname, '../evidence/post/N19-actual-draft.png'), fullPage: true });
});

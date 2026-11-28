import { expect, test } from '@playwright/test';
import { fixture, open } from '../support';

// Route 3 / T42 / T43: 25 rows, grouped queue, explicit recipient, local reminder; customer unchanged.
test('route 3: 25 rows, grouped clients, reminder draft → confirm without outbound sending', async ({ page }) => {
  await open(page, 'clients');
  await expect(page.getByText('ровно 25')).toBeVisible();
  await page.getByRole('tab', { name: /25 заявок/ }).click();
  await expect(page.getByRole('region', { name: '25 выбранных заявок' }).locator('tbody tr')).toHaveCount(25);
  await page.getByRole('tab', { name: /Очередь по клиентам/ }).click();
  const first = page.getByRole('radio').first();
  await first.check();
  await expect(page.getByText(/Исходные заявки C\d+/)).toBeVisible();
  await expect(page.getByText(/Фактическая метка показана отдельно/)).toBeVisible();
  const form = page.locator('form').filter({ hasText: 'Создать черновик напоминания' });
  await form.getByLabel('Ответственный').fill('M2');
  await form.getByLabel('Товарная группа').fill('зеркала');
  await form.getByLabel('Срок по местному времени').fill('2026-12-01T10:00');
  await form.getByRole('button', { name: 'Создать черновик напоминания' }).click();
  await expect(page.getByText(/Черновик создан\./)).toBeVisible();
  const row = page.getByRole('region', { name: 'Напоминания' }).locator('tbody tr').first();
  await expect(row.getByText('Черновик')).toBeVisible();
  await row.getByRole('button', { name: 'Подтвердить' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Запланировать' }).click();
  await expect(row.getByText('Запланировано')).toBeVisible();
  // No outbound channel actions exist: nothing can be sent to a client from the CRM screen.
  await expect(page.getByRole('button', { name: /Отправить|WhatsApp|e-?mail|SMS/i })).toHaveCount(0);
});

test('T43: workplace reminder keeps the quote customer separate from the recipient', async ({ page }) => {
  await open(page, 'workplace');
  await page.getByLabel(/Заказчик текущего предложения/).fill('NEW-CLIENT-1');
  await page.getByRole('radio', { name: /C\d+ · место 1/ }).check();
  await page.getByText('Создать локальное напоминание').click();
  await expect(page.getByText(/Заказчик текущего предложения: /)).toBeVisible();
  await expect(page.getByText(/Адресат напоминания — отдельная роль; заказчик не меняется/)).toBeVisible();
  await expect(page.getByLabel(/Заказчик текущего предложения/)).toHaveValue('NEW-CLIENT-1');
});

test('T44: a reminder for a specific remnant becomes stale when the remnant is taken; confirmation is blocked', async ({ page }) => {
  await open(page, 'clients');
  await page.getByRole('radio').first().check();
  const form = page.locator('form').filter({ hasText: 'Создать черновик напоминания' });
  await form.getByLabel('Тип предмета').selectOption('specific_remnant');
  await form.getByLabel('Номер свободного куска').fill('R006');
  await form.getByLabel('Ответственный').fill('M1');
  await form.getByLabel('Срок по местному времени').fill('2026-12-02T09:30');
  await form.getByRole('button', { name: 'Создать черновик напоминания' }).click();
  await expect(page.getByText(/Черновик создан/)).toBeVisible();
  await fixture(page, c => c.takeRemnant('R006'));
  await page.goto('/#/managers');
  await page.goto('/#/clients');
  const row = page.getByRole('region', { name: 'Напоминания' }).locator('tbody tr').filter({ hasText: 'R006' });
  await expect(row.getByText('Устарело')).toBeVisible();
  await expect(row.getByText(/больше не свободен — подтверждение заблокировано/)).toBeVisible();
  await expect(row.getByRole('button', { name: 'Подтвердить' })).toHaveCount(0);
});

test('validated_model policy that was not promoted is shown as a conflict, not as results', async ({ page }) => {
  await open(page, 'clients');
  await page.getByLabel('Политика отбора').selectOption('validated_model');
  await expect(page.getByRole('paragraph').filter({ hasText: 'Модель не доказала улучшение; зафиксирована reference-v1.' })).toBeVisible();
});

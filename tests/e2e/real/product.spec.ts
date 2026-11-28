import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';
import { expectNoPageOverflow, nb } from '../support';

/**
 * Real-backend acceptance of the visible UI. Requires a FRESH backend data dir.
 * No fixture is involved: every number comes from the running GlassFlow API.
 */
const PACK = path.resolve(__dirname, '../../../inputs/PACK_for_teams');
const FILES = [
  '1_ostatki/materials.csv',
  '1_ostatki/stock_open.csv',
  '1_ostatki/orders_open.csv',
  '2_assistant_crm/questions_open.csv',
  '2_assistant_crm/dialogs_open.csv',
  '2_assistant_crm/applications_open.csv',
  '2_assistant_crm/ksm_knowledge_base.json',
  '2_assistant_crm/questions_open_KEY.csv',
].map(file => path.join(PACK, file));

const shot = (page: Page, name: string) => page.screenshot({ path: path.resolve(__dirname, `../evidence/real/${name}.png`) });

async function importPack(page: Page, mode: 'source' | 'contest', name: string, copy = false) {
  await page.goto('/#/settings/data');
  await page.locator('input[type=file]').setInputFiles(FILES);
  await page.getByRole('button', { name: 'Проверить файлы' }).click();
  await expect(page.getByText('Ошибок не найдено')).toBeVisible();
  await page.getByLabel('Название снимка').fill(name);
  await page.getByLabel('Режим').selectOption(mode);
  if (copy) await page.getByLabel(/явно создать отдельную копию/).check();
  await page.getByRole('button', { name: /Создать снимок/ }).click();
  await expect(page.getByText(/Снимок создан|уже существует/)).toBeVisible();
}

async function selectDataset(page: Page, label: RegExp) {
  const select = page.locator('#dataset-select');
  const option = select.locator('option').filter({ hasText: label }).first();
  await select.selectOption({ value: (await option.getAttribute('value')) as string });
}

// Ordered (workers: 1) but not serial-abort: every scenario reports its own PASS/FAIL.
test.describe('real backend', () => {
  test('T01: import preview shows exact counts, excludes KEY, creates an immutable snapshot', async ({ page }) => {
    await page.goto('/#/settings/data');
    await page.locator('input[type=file]').setInputFiles(FILES);
    await page.getByRole('button', { name: 'Проверить файлы' }).click();
    for (const [label, value] of [['Остатки', '200'], ['Детали заказов', '298'], ['Заказы', '110'], ['Заявки CRM', '700'], ['Вопросы', '18'], ['Диалоги', '8']]) {
      await expect(page.locator('.metric').filter({ hasText: label }).first()).toContainText(value);
    }
    await expect(page.getByText('Файл с эталонными ответами исключён из рабочих данных.', { exact: true })).toBeVisible();
    await page.getByText('Исходное сообщение для поддержки', { exact: true }).click();
    await expect(page.getByText(/KEY\.csv: evaluation\/служебный файл исключен из runtime/)).toBeVisible();
    await page.getByText('Исходное сообщение для поддержки', { exact: true }).click();
    await shot(page, 'T01-import-preview');
    await page.getByLabel('Название снимка').fill('Пакет организаторов');
    await page.getByRole('button', { name: /Создать снимок/ }).click();
    await expect(page.getByText('Снимок создан')).toBeVisible();
    await page.getByRole('button', { name: 'Открыть набор' }).click();
    await expect(page.locator('.mode-badge')).toContainText('Исходный снимок · только чтение');
  });

  test('T02: re-importing the same bytes opens the existing snapshot instead of duplicating', async ({ page }) => {
    await importPack(page, 'source', 'Пакет организаторов (повтор)');
    await expect(page.getByText('Такой снимок уже существует — открыт существующий')).toBeVisible();
  });

  test('working copy is created explicitly and selected', async ({ page }) => {
    await page.goto('/#/settings/data');
    await page.getByRole('button', { name: 'Копия' }).first().click();
    await page.getByRole('dialog').getByRole('button', { name: 'Создать рабочую копию' }).click();
    await expect(page.locator('.mode-badge')).toContainText('Рабочая копия');
  });

  test('T40/T42: 25 picks, grouped queue, open-label precision shown as open-set only', async ({ page }) => {
    await page.goto('/#/clients');
    await selectDataset(page, /Пакет организаторов · Исходный/);
    await expect(page.getByText('ровно 25')).toBeVisible();
    await expect(page.locator('.metric').filter({ hasText: 'Уникальных клиентов' })).toContainText('15');
    await expect(page.locator('.metric').filter({ hasText: 'Precision@25' })).toContainText('80,0');
    await page.getByRole('tab', { name: /25 заявок/ }).click();
    await expect(page.getByRole('region', { name: '25 выбранных заявок' }).locator('tbody tr')).toHaveCount(25);
    await shot(page, 'T40-clients');
  });

  test('T45: seven manager metrics with denominators and drill-down rows', async ({ page }) => {
    await page.goto('/#/managers');
    await selectDataset(page, /Пакет организаторов · Исходный/);
    for (const label of ['Число заявок', 'Среднее время ответа', 'Конверсия', 'Доля возвратов', 'Средний чек', 'Доля жалоб', 'Доля скидок'])
      await expect(page.getByRole('columnheader', { name: new RegExp(label) })).toBeVisible();
    await expect(page.getByRole('rowheader', { name: 'M1' })).toBeVisible();
    await page.getByRole('button', { name: /^M1: .*%/ }).first().click();
    await expect(page.getByRole('dialog').getByRole('region', { name: 'Исходные строки показателя' }).locator('tbody tr').first()).toBeVisible();
    await shot(page, 'T45-drilldown');
    await page.keyboard.press('Escape');
    await expectNoPageOverflow(page);
  });

  test('T43: local reminder in the working copy; draft → scheduled; no outbound action', async ({ page }) => {
    await page.goto('/#/clients');
    await selectDataset(page, /Рабочая копия/);
    await page.getByRole('radio').first().check();
    const form = page.locator('form').filter({ hasText: 'Создать черновик напоминания' });
    await form.getByLabel('Ответственный').fill('M2');
    await form.getByLabel('Товарная группа').fill('зеркала');
    await form.getByLabel('Срок (Asia/Qyzylorda)').fill('2026-12-01T10:00');
    await form.getByRole('button', { name: 'Создать черновик напоминания' }).click();
    await expect(page.getByText(/Черновик создан/)).toBeVisible();
    const row = page.getByRole('region', { name: 'Напоминания' }).locator('tbody tr').first();
    await row.getByRole('button', { name: 'Подтвердить' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Запланировать' }).click();
    await expect(row.getByText('Запланировано')).toBeVisible();
  });

  test('T28: workplace quote 450×370 clear-6 with euro edge = 1 988,00', async ({ page }) => {
    await page.goto('/#/workplace');
    await selectDataset(page, /Рабочая копия/);
    const product = page.getByLabel(/Товар каталога/);
    await expect(product.locator('option')).not.toHaveCount(1);
    await product.selectOption({ label: 'Стекло 6 мм прозрачное' });
    await page.getByLabel('Длина', { exact: true }).fill('450');
    await page.getByLabel('Ширина', { exact: true }).fill('370');
    await page.getByLabel('Обработка').selectOption('euro_edge');
    await page.getByRole('button', { name: 'Рассчитать' }).click();
    await expect.poll(async () => nb(await page.locator('.quote-total strong').textContent())).toBe('1 988,00 ₸');
    await page.getByLabel('Длина', { exact: true }).fill('451');
    await page.getByRole('button', { name: /Пересчитать/ }).click();
    await expect.poll(async () => nb(await page.locator('.quote-total strong').textContent())).toBe('1 991,76 ₸');
    await shot(page, 'T28-quote');
  });

  test('cutting workspace lists real remnants with locations (R05)', async ({ page }) => {
    await page.goto('/#/cutting');
    await selectDataset(page, /Рабочая копия/);
    await expect(page.getByRole('region', { name: 'Остатки склада' })).toBeVisible();
    await expect(page.getByText(/A-1|Стеллаж A, ячейка 1/).first()).toBeVisible();
  });

  test('settings: AI check reports the real state; backup is created with integrity', async ({ page }) => {
    await page.goto('/#/settings/ai');
    await page.getByRole('button', { name: 'Проверить соединение' }).click();
    await expect(page.getByText(/Провайдер доступен|Провайдер недоступен|Сервис недоступен/).first()).toBeVisible();
    await page.goto('/#/settings/system');
    await page.getByRole('button', { name: 'Создать резервную копию сейчас' }).click();
    await expect(page.getByText(/Копия создана: .* · целостность ok/)).toBeVisible();
  });

  test('route 4 (CRM module only): contest snapshot → run → export picks.csv of that run', async ({ page }) => {
    await importPack(page, 'contest', 'Конкурсный снимок (открытый пакет)');
    await page.getByRole('button', { name: 'Открыть набор' }).click();
    await page.goto('/#/runs');
    for (const name of ['Раскрой', 'Ассистент', 'Контроль диалогов', 'Карточки остатков']) await page.getByLabel(new RegExp(name)).uncheck();
    await page.getByRole('button', { name: 'Запустить прогон' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Запустить' }).click();
    await expect(page.getByText('Все запрошенные модули завершены')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole('region', { name: 'Модули прогона' }).getByRole('row', { name: /Отбор CRM/ })).toContainText('Готово');
    await expect(page.getByText('Остановка подтверждена')).toHaveCount(0);
    await page.getByRole('button', { name: 'Проверить и подготовить файлы' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Проверить и подготовить' }).click();
    await expect(page.getByText(/Частичный пакет|Пакет готов|Экспорт заблокирован/)).toBeVisible({ timeout: 60_000 });
    await shot(page, 'route4-crm-export');
    const picks = page.locator('ul.downloads li').filter({ hasText: 'picks.csv' });
    await expect(picks).toBeVisible();
    const [download] = await Promise.all([page.waitForEvent('download'), picks.getByRole('link', { name: 'Скачать' }).click()]);
    const file = await download.path();
    const text = (await import('node:fs')).readFileSync(file!, 'utf8');
    expect(text.startsWith('﻿')).toBe(false);
    const lines = text.trim().split(/\r?\n/);
    expect(lines[0]).toBe('app_id');
    expect(new Set(lines.slice(1)).size).toBe(25);
  });
});

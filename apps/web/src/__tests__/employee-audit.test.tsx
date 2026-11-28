import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ApiProvider, makeApi } from '../api/context';
import type { Transport } from '../api/transport';
import { SystemSection } from '../features/settings/SystemSection';
import { DataSection } from '../features/settings/DataSection';
import { assistantParameterLabel, assistantParameterValue } from '../features/workplace/AssistantPanel';
import { PlanInsights } from '../features/cutting/PlanInsights';

afterEach(cleanup);

function view(element: React.ReactNode, responses: Record<string, unknown>) {
  const transport: Transport = { kind: 'http', request: async request => ({
    status: 200, headers: {}, body: responses[request.path] ?? [],
  }) };
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ApiProvider value={makeApi(transport)}>{element}</ApiProvider>
  </QueryClientProvider>);
}

it('keeps unknown audit events honest and their exact codes and structured details out of the main view', async () => {
  view(<SystemSection />, { '/system/journal': [
    { at: '2026-11-28T10:00:00Z', level: 'info', event: 'unreleased.new_event', detail: '{"job":"secret-id"}', correlation_id: 'audit-support-id' },
  ] });
  expect(await screen.findByText('Изменение записи')).toBeVisible();
  expect(screen.getByText('Не указан в журнале')).toBeVisible();
  expect(screen.getByText('Событие: unreleased.new_event')).not.toBeVisible();
  expect(screen.getByText('{"job":"secret-id"}')).not.toBeVisible();
  fireEvent.click(screen.getByText('Технические подробности события'));
  expect(screen.getByText('Событие: unreleased.new_event')).toBeVisible();
  expect(screen.getByText('{"job":"secret-id"}')).toBeVisible();
  expect(screen.getByText('Номер обращения: audit-support-id')).toBeVisible();
});

it('shows named datasets while retaining their exact technical identity in closed support details', async () => {
  const id = 'f3334321-0808-4762-bc11-000000000003';
  view(<DataSection />, { '/datasets': [{ dataset_id: id, name: 'Заказы цеха', mode: 'workspace', source_hashes: {}, row_counts: {}, created_at: '2026-11-28T10:00:00Z' }] });
  expect(await screen.findByText('Заказы цеха')).toBeVisible();
  expect(screen.getByText(`Номер набора: ${id}`)).not.toBeVisible();
  fireEvent.click(screen.getByText('Сведения о наборе для поддержки'));
  expect(screen.getByText(`Номер набора: ${id}`)).toBeVisible();
});

it('clarifies missing fields and structured assistant values without inventing a resolved parameter', () => {
  expect(assistantParameterLabel('dimensions_unit')).toBe('Единицы размеров: мм, см или м');
  expect(assistantParameterLabel('new_unrecognized_key')).toContain('уточнит менеджер');
  expect(assistantParameterValue('processing', 'euro_edge')).toBe('Евро-кромка');
  expect(assistantParameterValue('processing', 'none')).toBe('Без обработки');
  expect(assistantParameterValue('selected_sides', 'top,bottom')).toBe('Верхняя, Нижняя');
  expect(assistantParameterValue('selected_sides', 'long1,short1')).toBe('Одна длинная сторона, Одна короткая сторона');
  expect(assistantParameterValue('width_mm', { value: 450 })).toBe('Параметр требует проверки менеджера');
  expect(assistantParameterValue('width_mm', '{"value":450}')).toBe('Параметр требует проверки менеджера');
  expect(assistantParameterValue('width_mm', '450')).toBe('450');
  expect(assistantParameterValue('catalog_product_id', 'glass_internal_4', 'Стекло 4 мм')).toBe('Стекло 4 мм');
});

it('uses supplied material names for the real requirements projection and retains codes only for support', async () => {
  const reference = { dataset_id: 'dataset', plan_id: 'plan', revision: 3, inventory_version: 'stock-v1' };
  view(<PlanInsights datasetId="dataset" planId="plan" revision={3} materialNames={{ 'clear-4': 'Стекло прозрачное 4 мм' }} />, {
    '/plans/plan/new-requirements': { ...reference, is_active: true, scope: 'active', plan_status: 'committed', disclaimer_ru: 'Исходные сведения', total_quantity: 1, total_area_mm2: 10000,
      rows: [{ material_id: 'clear-4', dimensions: { length_mm: 100, width_mm: 100 }, quantity: 1, part_ids: ['P012'], order_ids: ['O002'], area_mm2: 10000, reason_code: 'LIMITED_SEARCH', reason_ru: 'Поиск ограничен временем' }] },
    '/plans/plan/geometry-margins': { ...reference, placements: [], trim_mm: 5, gap_mm: 3, tempered_tolerance_mm: 2, note_ru: 'Запас не является вероятностью брака.' },
  });
  const details = screen.getByText(/Требуется новый материал и геометрический запас/).closest('details')!;
  details.open = true;
  fireEvent(details, new Event('toggle'));
  expect(await screen.findByText('Стекло прозрачное 4 мм')).toBeVisible();
  expect(screen.getByText('clear-4')).not.toBeVisible();
  fireEvent.click(screen.getByText('Служебный номер материала'));
  expect(screen.getByText('clear-4')).toBeVisible();
});

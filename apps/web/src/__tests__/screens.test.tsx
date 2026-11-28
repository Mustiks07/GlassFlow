import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { App, createQueryClient } from '../App';
import { makeApi } from '../api/context';
import { createFixtureTransport } from '../api/fixtures/transport';
import { TransportFailure, type Transport } from '../api/transport';
import { useAppStore } from '../state/store';

const nb = (text: string | null) => (text ?? '').replace(/[  ]/g, ' ');

function renderWith(transport: Transport) {
  return render(<App api={makeApi(transport)} queryClient={createQueryClient()} />);
}

beforeEach(() => {
  window.localStorage.clear();
  useAppStore.setState({ datasetId: null, quoteDrafts: {}, reminderDrafts: {}, activePlanIds: {}, lastRunIds: {} });
  window.location.hash = '';
});
afterEach(() => cleanup());

describe('honest states without backend', () => {
  it('shows a recoverable error instead of invented data when the API is down', async () => {
    const down: Transport = { kind: 'http', request: async () => { throw new TransportFailure('x', 'offline'); } };
    renderWith(down);
    expect(await screen.findByText('Нет связи с приложением', {}, { timeout: 4000 })).toBeInTheDocument();
    expect((await screen.findAllByText(/Нет связи/, {}, { timeout: 8000 })).length).toBeGreaterThan(0);
    expect(screen.queryByText(/ТЕСТОВЫЙ РЕЖИМ/)).not.toBeInTheDocument();
  }, 15000);

  it('reports a not-yet-delivered module as such (501), not as success', async () => {
    const transport: Transport = {
      kind: 'http',
      request: async req => {
        if (req.path === '/datasets') return { status: 200, headers: { 'content-type': 'application/json' }, body: [{ dataset_id: 'd1', name: 'Набор', mode: 'workspace', source_hashes: {}, row_counts: {} }] };
        if (req.path === '/ready') return { status: 200, headers: { 'content-type': 'application/json' }, body: { status: 'foundation', database: true, business_modules_ready: false } };
        return { status: 501, headers: { 'content-type': 'application/json' }, body: { code: 'FEATURE_NOT_IMPLEMENTED', message_ru: 'Модуль cutting.list_remnants еще не реализован в каркасе проекта.', correlation_id: 'c1' } };
      },
    };
    useAppStore.setState({ datasetId: 'd1' });
    window.location.hash = '#/cutting';
    renderWith(transport);
    expect((await screen.findAllByText(/Модуль не подключен/, {}, { timeout: 4000 })).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Операция недоступна в установленной версии/).length).toBeGreaterThan(0);
  });
});

describe('fixture transport (explicit test mode)', () => {
  it('marks every screen as fixture mode', async () => {
    renderWith(createFixtureTransport());
    expect(await screen.findByText(/ТЕСТОВЫЙ РЕЖИМ FIXTURE/)).toBeInTheDocument();
  });

  it('calculates, marks the old total stale after a size change, and shows a new revision', async () => {
    useAppStore.setState({ datasetId: 'ds-work-fixture' });
    renderWith(createFixtureTransport());
    const product = await screen.findByLabelText(/Товар каталога/);
    await waitFor(() => expect(within(product as HTMLSelectElement).getAllByRole('option').length).toBeGreaterThan(2));
    fireEvent.change(product, { target: { value: 'steklo-6-prozrachnoe' } });
    fireEvent.change(screen.getByLabelText('Длина'), { target: { value: '45 см' } });
    fireEvent.change(screen.getByLabelText('Ширина'), { target: { value: '370' } });
    fireEvent.change(screen.getByLabelText('Обработка'), { target: { value: 'euro_edge' } });
    expect(screen.getByText(/45 см → 450 мм/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
    await waitFor(() => expect(nb(document.querySelector('.quote-total strong')!.textContent)).toBe('1 988,00 ₸'));
    expect(await screen.findByText('R006')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Длина'), { target: { value: '451' } });
    expect(screen.getAllByText(/не является новым итогом/).length).toBeGreaterThan(0);
    expect(document.querySelector('.quote-total strong')).toHaveClass('strike');
    fireEvent.click(screen.getByRole('button', { name: /Пересчитать/ }));
    await waitFor(() => expect(nb(document.querySelector('.quote-total strong')!.textContent)).toBe('1 991,76 ₸'));
    expect(screen.getByText(/ревизия 2/)).toBeInTheDocument();
    expect(await screen.findByText(/Свободного подходящего куска нет/)).toBeInTheDocument();
  }, 15000);

  it('shows unmapped catalog material distinctly from "no stock" and NEW', async () => {
    useAppStore.setState({ datasetId: 'ds-work-fixture' });
    renderWith(createFixtureTransport());
    const product = await screen.findByLabelText(/Товар каталога/);
    await waitFor(() => expect(within(product as HTMLSelectElement).getAllByRole('option').length).toBeGreaterThan(2));
    fireEvent.change(product, { target: { value: 'steklo-riflenoe-8' } });
    fireEvent.change(screen.getByLabelText('Длина'), { target: { value: '500' } });
    fireEvent.change(screen.getByLabelText('Ширина'), { target: { value: '500' } });
    fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
    expect(await screen.findByText('Соответствие складу не подтверждено. Наличие материала нужно уточнить')).toBeInTheDocument();
    expect(screen.getByText('Нет соответствия каталога складу')).toBeInTheDocument();
    expect(nb(document.querySelector('.quote-total strong')!.textContent)).toBe('не определен');
  });

  it('renders all seven manager metrics with denominators', async () => {
    useAppStore.setState({ datasetId: 'ds-source-fixture' });
    window.location.hash = '#/managers';
    renderWith(createFixtureTransport());
    const table = await screen.findByRole('table', {}, { timeout: 4000 }).catch(() => null);
    expect(table ?? (await screen.findByText('Число заявок'))).toBeTruthy();
    for (const label of ['Число заявок', 'Среднее время ответа', 'Конверсия', 'Доля возвратов', 'Средний чек', 'Доля жалоб', 'Доля скидок']) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText(/отдельный показатель, не средний чек/)).toBeInTheDocument();
  });

  it('keeps the quote customer separate from the reminder recipient', async () => {
    useAppStore.setState({ datasetId: 'ds-work-fixture' });
    window.location.hash = '#/clients';
    renderWith(createFixtureTransport());
    expect(await screen.findByText('ровно 25')).toBeInTheDocument();
    const radios = await screen.findAllByRole('radio');
    fireEvent.click(radios[0]);
    expect(await screen.findByText(/Напоминание для/)).toBeInTheDocument();
    expect(screen.getByText(/Сообщения клиенту не отправляются/)).toBeInTheDocument();
  });
});

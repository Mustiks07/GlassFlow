import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { App } from './App';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows real API readiness without claiming unfinished modules are complete', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    json: async () => url.endsWith('/health')
      ? { status: 'ok', app: 'GlassFlow', version: '0.1.0' }
      : { status: 'foundation', database: true, business_modules_ready: false },
  })));
  render(<App />);
  expect(await screen.findByText('Подключена')).toBeInTheDocument();
  expect(screen.getByText('Ожидают реализации')).toBeInTheDocument();
  expect(screen.getByText('Каркас проекта')).toBeInTheDocument();
});

it('shows a recoverable error instead of invented healthy status', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('Соединение отклонено'); }));
  render(<App />);
  expect(await screen.findByText('API недоступен')).toBeInTheDocument();
  expect(screen.queryByText('Подключена')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Проверить связь' })).toBeEnabled();
});

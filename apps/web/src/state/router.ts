/**
 * Hash routing: works with the static build served by FastAPI StaticFiles (no SPA
 * fallback needed) and survives refresh/restart. #/section[/sub][?query]
 */
import { useSyncExternalStore } from 'react';

export type Section = 'workplace' | 'cutting' | 'sales' | 'clients' | 'managers' | 'runs' | 'settings';

export const SECTIONS: { id: Section; label: string; short: string }[] = [
  { id: 'workplace', label: 'Рабочее место', short: 'Запрос и расчет' },
  { id: 'cutting', label: 'Остатки и раскрой', short: 'Склад, схема, план' },
  { id: 'sales', label: 'Продажа остатков', short: 'Карточки и покупатели' },
  { id: 'clients', label: 'Клиенты', short: 'Отбор и напоминания' },
  { id: 'managers', label: 'Менеджеры', short: 'M1–M5, семь показателей' },
  { id: 'runs', label: 'Прогоны', short: 'Конкурсный запуск' },
  { id: 'settings', label: 'Настройки', short: 'Данные, AI, система' },
];

export interface Route {
  section: Section;
  sub: string | null;
  params: URLSearchParams;
}

function parse(hash: string): Route {
  const clean = hash.replace(/^#\/?/, '');
  const [pathPart, queryPart = ''] = clean.split('?');
  const [first, second] = pathPart.split('/');
  const section = (SECTIONS.find(item => item.id === first)?.id ?? 'workplace') as Section;
  return { section, sub: second || null, params: new URLSearchParams(queryPart) };
}

function subscribe(callback: () => void) {
  window.addEventListener('hashchange', callback);
  return () => window.removeEventListener('hashchange', callback);
}

let cachedHash = '';
let cachedRoute: Route = parse('');

function snapshot(): Route {
  const hash = window.location.hash;
  if (hash !== cachedHash) {
    cachedHash = hash;
    cachedRoute = parse(hash);
  }
  return cachedRoute;
}

export function useRoute(): Route {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

export function href(section: Section, sub?: string | null, params?: Record<string, string>): string {
  const query = params ? new URLSearchParams(params).toString() : '';
  return `#/${section}${sub ? `/${sub}` : ''}${query ? `?${query}` : ''}`;
}

export function navigate(section: Section, sub?: string | null, params?: Record<string, string>) {
  window.location.hash = href(section, sub, params);
}

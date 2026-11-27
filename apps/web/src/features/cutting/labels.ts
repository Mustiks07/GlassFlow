import type { UnplacedReason } from '../../api/types';

export const REASON_LABEL: Record<string, string> = {
  material_mismatch: 'Нет остатков этого материала',
  size_does_not_fit: 'Размер не проходит ни в один свободный кусок',
  premium_on_defect: 'Премиум-деталь нельзя на дефектный кусок',
  occupied_by_reservation: 'Подходящие куски заняты текущими резервами',
  lock_conflict: 'Конфликт с закреплениями',
  search_limited: 'Поиск не нашел решение за лимит (это не доказательство невозможности)',
  unknown: 'Причина не определена (UNKNOWN не означает невозможность)',
  no_free_whole_remnant: 'Нет свободного целого куска при текущих закреплениях',
  tempered_tolerance: 'Калёное: нет куска в допуске ±2 мм',
  unmapped_material: 'Товар каталога не сопоставлен складскому материалу',
};

export function reasonLabel(code: string | UnplacedReason): string {
  return REASON_LABEL[code] ?? code;
}

export const REMNANT_STATUS_LABEL: Record<string, string> = {
  available: 'Свободен',
  reserved: 'Зарезервирован',
  consumed: 'Списан',
  withdrawn: 'Исключен',
};

export const SEARCH_STATUS_LABEL: Record<string, string> = {
  feasible: 'Найдено допустимое решение',
  optimal_in_pool: 'Оптимум в пуле шаблонов (не глобальный оптимум)',
  proven_optimal: 'Доказанный оптимум',
  limited: 'Допустимое решение, поиск ограничен лимитом',
  infeasible: 'Решение не найдено',
};

export const PLAN_STATUS_LABEL: Record<string, string> = {
  draft: 'Черновик',
  validated: 'Проверен',
  committed: 'Подтвержден',
  superseded: 'Заменен',
  invalid: 'Недопустим (черновик можно исправить)',
};

/** "Стеллаж A, ячейка 6" → rack/cell when recognisable; otherwise the raw text only. */
export function parseLocation(raw: string): { rack: string | null; cell: string | null } {
  const rack = /стеллаж\s*([A-Za-zА-Яа-я0-9-]+)/i.exec(raw)?.[1] ?? null;
  const cell = /ячейка\s*([A-Za-zА-Яа-я0-9-]+)/i.exec(raw)?.[1] ?? null;
  return { rack, cell };
}

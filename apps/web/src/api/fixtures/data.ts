/**
 * TEST FIXTURE DATA — synthetic, for UI tests and `pnpm dev:fixture` only.
 * Not organiser data, not a backend result, never bundled in a normal build.
 * Material ids/rates mirror the public case materials so the screens look realistic;
 * remnants, parts, clients and applications are invented for tests.
 */
import type {
  ApplicationRow,
  Buyer,
  CatalogProduct,
  CutPlan,
  Dataset,
  Material,
  Part,
  Placement,
  Remnant,
} from '../types';

export const FIXTURE_TAG = 'fixture';

export const materials: Material[] = [
  { material_id: 'clear-4', name: 'Стекло 4 мм прозрачное', thickness_mm: 4, unit_price_tg: '4500', tempered: false },
  { material_id: 'clear-6', name: 'Стекло 6 мм прозрачное', thickness_mm: 6, unit_price_tg: '8000', tempered: false },
  { material_id: 'clear-8', name: 'Стекло 8 мм прозрачное', thickness_mm: 8, unit_price_tg: '12000', tempered: false },
  { material_id: 'grey-8', name: 'Стекло серое 8 мм', thickness_mm: 8, unit_price_tg: '20000', tempered: false },
  { material_id: 'mirror-4', name: 'Зеркало 4 мм', thickness_mm: 4, unit_price_tg: '9500', tempered: false },
  { material_id: 'temp-6', name: 'Стекло калёное 6 мм', thickness_mm: 6, unit_price_tg: '15500', tempered: true },
];

function remnant(id: string, material: string, l: number, w: number, rack: string, cell: number, defect = false, age = 100): Remnant {
  return {
    dataset_id: '',
    remnant_id: id,
    material_id: material,
    dimensions: { length_mm: l, width_mm: w },
    age_days: age,
    defect,
    location_raw: `Стеллаж ${rack}, ячейка ${cell}`,
    status: 'available',
    version: 0,
  };
}

export function makeRemnants(datasetId: string): Remnant[] {
  return [
    remnant('R001', 'clear-8', 790, 590, 'A', 1),
    remnant('R002', 'grey-8', 840, 630, 'A', 2, true),
    remnant('R003', 'clear-6', 840, 460, 'A', 3, true),
    remnant('R004', 'clear-4', 520, 390, 'A', 4),
    remnant('R005', 'mirror-4', 1200, 800, 'A', 5),
    remnant('R006', 'clear-6', 460, 380, 'A', 6),
    remnant('R007', 'clear-6', 900, 700, 'B', 1),
    remnant('R008', 'temp-6', 602, 401, 'B', 2),
    remnant('R009', 'clear-4', 1500, 1000, 'B', 3),
    remnant('R010', 'mirror-4', 700, 500, 'B', 4),
    remnant('R011', 'clear-8', 1000, 600, 'B', 5),
    remnant('R012', 'grey-8', 500, 300, 'C', 1),
    remnant('R013', 'clear-6', 650, 420, 'C', 2),
    remnant('R014', 'clear-4', 400, 300, 'C', 3),
    remnant('R015', 'mirror-4', 900, 600, 'C', 4),
    remnant('R016', 'clear-8', 700, 450, 'C', 5),
  ].map(item => ({ ...item, dataset_id: datasetId }));
}

function part(id: string, order: string, material: string, l: number, w: number, premium = false, type = 'вставка'): Part {
  return { part_id: id, order_id: order, material_id: material, dimensions: { length_mm: l, width_mm: w }, premium, product_type: type };
}

export const parts: Part[] = [
  part('P0001', 'O001', 'mirror-4', 660, 400, true, 'зеркало'),
  part('P0002', 'O002', 'clear-6', 880, 340),
  part('P0003', 'O002', 'clear-6', 400, 300),
  part('P0004', 'O003', 'clear-8', 760, 280),
  part('P0005', 'O003', 'clear-8', 760, 270),
  part('P0006', 'O004', 'clear-4', 1400, 600, false, 'полка'),
  part('P0007', 'O004', 'clear-4', 600, 300, false, 'полка'),
  part('P0008', 'O005', 'temp-6', 600, 400, false, 'дверца'),
  part('P0009', 'O006', 'grey-8', 820, 610, true, 'столешница'),
  part('P0010', 'O007', 'mirror-4', 1150, 750, false, 'зеркало'),
  part('P0011', 'O008', 'clear-6', 2000, 1200, false, 'перегородка'),
  part('P0012', 'O009', 'clear-8', 950, 560),
];

export const planPlacements: Placement[] = [
  { part_id: 'P0001', remnant_id: 'R010', x_mm: 5, y_mm: 5, rot: 0, lock_kind: 'none' },
  { part_id: 'P0002', remnant_id: 'R007', x_mm: 5, y_mm: 5, rot: 0, lock_kind: 'none' },
  { part_id: 'P0003', remnant_id: 'R007', x_mm: 5, y_mm: 348, rot: 0, lock_kind: 'none' },
  { part_id: 'P0004', remnant_id: 'R001', x_mm: 5, y_mm: 5, rot: 0, lock_kind: 'none' },
  { part_id: 'P0005', remnant_id: 'R001', x_mm: 5, y_mm: 288, rot: 0, lock_kind: 'none' },
  { part_id: 'P0006', remnant_id: 'R009', x_mm: 5, y_mm: 5, rot: 0, lock_kind: 'none' },
  { part_id: 'P0007', remnant_id: 'R009', x_mm: 5, y_mm: 608, rot: 0, lock_kind: 'none' },
  { part_id: 'P0008', remnant_id: 'R008', x_mm: null, y_mm: null, rot: 0, lock_kind: 'none' },
  { part_id: 'P0009', remnant_id: 'NEW', x_mm: null, y_mm: null, rot: null, lock_kind: 'none' },
  { part_id: 'P0010', remnant_id: 'R005', x_mm: 5, y_mm: 5, rot: 0, lock_kind: 'none' },
  { part_id: 'P0011', remnant_id: 'NEW', x_mm: null, y_mm: null, rot: null, lock_kind: 'none' },
  { part_id: 'P0012', remnant_id: 'R011', x_mm: 5, y_mm: 5, rot: 0, lock_kind: 'none' },
];

export function makePlan(datasetId: string, planId = 'PLAN-1', revision = 1): CutPlan {
  return {
    dataset_id: datasetId,
    plan_id: planId,
    revision,
    status: 'committed',
    placements: planPlacements.map(item => ({ ...item })),
    metrics: {
      covered_area_mm2: 3_755_700,
      total_area_mm2: 6_655_900,
      coverage: 0.5643,
      replacement_value_tg: '40125.60',
      invalid: 0,
      missing: 0,
      fully_covered_orders: 7,
    },
    free_original_remnant_ids: ['R002', 'R003', 'R004', 'R006', 'R012', 'R013', 'R014', 'R015', 'R016'],
    search_status: 'limited',
    new_reasons: { P0009: 'premium_on_defect', P0011: 'size_does_not_fit' },
    excluded_remnant_ids: [],
  };
}

export const catalog: CatalogProduct[] = [
  product('steklo-6-prozrachnoe', 'Стекло 6 мм прозрачное', 'Стекло', [{ price_type: 'per_m2', amount_tg: '8000' }]),
  product('steklo-8-prozrachnoe', 'Стекло 8 мм прозрачное', 'Стекло', [{ price_type: 'per_m2', amount_tg: '12000' }]),
  product('steklo-seroe', 'Стекло серое', 'Стекло', [{ price_type: 'per_m2', amount_tg: '10000' }]),
  product('steklo-seroe-8', 'Стекло серое 8 мм', 'Стекло', [{ price_type: 'per_m2', amount_tg: '20000' }]),
  product('steklo-riflenoe-8', 'Стекло рифлёное прозрачное 8 мм', 'Стекло', [
    { price_type: 'per_sheet', amount_tg: '170000' },
    { price_type: 'per_m2', amount_tg: null },
  ]),
  product('ugolok-bolshoi', 'Уголок для сборки рамочного фасада, большой', 'Фурнитура', [
    { price_type: 'retail_unit', amount_tg: '350' },
    { price_type: 'bulk_unit', amount_tg: '300', minimum_quantity: 100 },
  ]),
  product('ab1012', 'Профиль AB1012', 'Профиль', [{ price_type: 'per_m', amount_tg: null }]),
];

function product(id: string, name: string, category: string, prices: CatalogProduct['prices']): CatalogProduct {
  return { catalog_product_id: id, name, category, prices, evidence: [{ source: 'kb', source_version: 'sha256:fixture-kb', record_id: id, field: 'цена' }] };
}

const MANAGERS = ['M1', 'M2', 'M3', 'M4', 'M5'];
const GROUPS = ['калёное', 'зеркала', 'рифлёное', 'стекло', 'фурнитура'];
const CHANNELS = ['WhatsApp', 'сайт', 'звонок'];
const TYPES = ['частный', 'мебельная фабрика', 'магазин', 'дизайн-студия'];

/** 60 synthetic application rows; deterministic pseudo-random. */
export function makeApplications(): ApplicationRow[] {
  let seed = 7;
  const rnd = (n: number) => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed % n;
  };
  const rows: ApplicationRow[] = [];
  for (let i = 0; i < 60; i += 1) {
    const sold = rnd(3) > 0 ? '1' : '0';
    rows.push({
      source_row: i + 2,
      app_id: `A${String(i + 1).padStart(4, '0')}`,
      client_id: `C${String(100 + (i % 22)).padStart(3, '0')}`,
      день_года: String(i * 3),
      manager: MANAGERS[i % 5],
      группа_товара: GROUPS[rnd(5)],
      сумма_тг: String(5000 + rnd(150) * 1000),
      канал: CHANNELS[rnd(3)],
      тип_клиента: TYPES[rnd(4)],
      прошлых_заявок: String(rnd(6)),
      дней_с_последнего_контакта: String(10 + rnd(120)),
      жалоба: rnd(7) === 0 ? '1' : '0',
      доставка: String(rnd(2)),
      скидка: rnd(4) === 0 ? '1' : '0',
      вернулся_за_60_дней: String(rnd(2)),
      ответ_через_мин: String(5 + rnd(120)),
      продано: sold,
    });
  }
  return rows;
}

export const buyers: Buyer[] = [
  { buyer_id: 'B-FX-1', name: 'ТЕСТ: Мебельная фабрика «Пример»', city: 'Астана', category: 'мебельная фабрика', url: 'https://example.org/furniture', why: 'Фикстура: стеклянные фасады и полки.', source_url: 'https://example.org/furniture', score: 80 },
  { buyer_id: 'B-FX-2', name: 'ТЕСТ: Дизайн-студия «Образец»', city: 'Астана', category: 'дизайн-студия', url: 'https://example.org/design', why: 'Фикстура: зеркальные панели в интерьере.', source_url: 'https://example.org/design', score: 70 },
  { buyer_id: 'B-FX-3', name: 'ТЕСТ: Окна и двери «Шаблон»', city: 'Астана', category: 'окна и двери', url: 'https://example.org/windows', why: 'Фикстура: стеклянные вставки дверей.', source_url: 'https://example.org/windows', score: 75 },
  { buyer_id: 'B-FX-4', name: 'ТЕСТ: Кафе «Модель»', city: 'Алматы', category: 'кафе или ресторан', url: 'https://example.org/cafe', why: 'Фикстура: стекло для столешниц.', source_url: 'https://example.org/cafe', score: 55 },
  { buyer_id: 'B-FX-5', name: 'ТЕСТ: Строительная компания «Макет»', city: 'Астана', category: 'строительная компания', url: 'https://example.org/build', why: 'Фикстура: перегородки в офисах.', source_url: 'https://example.org/build', score: 65 },
];

export function makeDatasets(): Dataset[] {
  const hashes = {
    materials: 'a1'.repeat(32),
    stock: 'b2'.repeat(32),
    orders: 'c3'.repeat(32),
    questions: 'd4'.repeat(32),
    dialogs: 'e5'.repeat(32),
    applications: 'f6'.repeat(32),
    kb: '07'.repeat(32),
  };
  const counts = { materials: 6, stock: 16, orders: 12, distinct_orders: 9, questions: 18, dialogs: 8, applications: 60, kb: 1 };
  return [
    { dataset_id: 'ds-source-fixture', name: 'Открытый пакет (ТЕСТ fixture)', mode: 'source', source_hashes: hashes, row_counts: counts, created_at: '2026-11-27T05:00:00Z', version: 0, parent_id: null, kb_version: 'sha256:fixture-kb' },
    { dataset_id: 'ds-work-fixture', name: 'Рабочая копия (ТЕСТ fixture)', mode: 'workspace', source_hashes: hashes, row_counts: counts, created_at: '2026-11-27T05:10:00Z', version: 0, parent_id: 'ds-source-fixture', kb_version: 'sha256:fixture-kb' },
    { dataset_id: 'ds-contest-fixture', name: 'Конкурсный снимок (ТЕСТ fixture)', mode: 'contest', source_hashes: hashes, row_counts: counts, created_at: '2026-11-27T05:20:00Z', version: 0, parent_id: null, kb_version: 'sha256:fixture-kb' },
  ];
}

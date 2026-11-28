import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useApi } from '../../api/context';
import { formatAreaM2, formatDims, formatInt, formatMm } from '../../lib/format';
import { Button, EmptyState, ErrorState, LoadingState, StatusBadge, TableWrap } from '../../ui/kit';

// Exact additive Python DTOs; root regenerates shared schemas after integration.
interface PlanReference {
  dataset_id: string;
  plan_id: string;
  revision: number;
  inventory_version: string;
}

interface NewRequirements extends PlanReference {
  plan_status: string;
  is_active: boolean;
  scope: 'active' | 'proposal' | 'historical';
  rows: {
    material_id: string;
    dimensions: { length_mm: number; width_mm: number };
    quantity: number;
    part_ids: string[];
    order_ids: string[];
    area_mm2: number;
    reason_code: string;
    reason_ru: string;
  }[];
  total_area_mm2: number;
  total_quantity: number;
  disclaimer_ru: string;
}

interface PlanMargins extends PlanReference {
  placements: {
    part_id: string;
    remnant_id: string;
    tempered: boolean;
    margin_kind: 'cut_geometry' | 'whole_piece_tolerance';
    edge_clearance_mm?: number | null;
    neighbor_clearance_mm?: number | null;
    minimum_excess_mm: number;
    dimension_deviation_mm?: number | null;
  }[];
  trim_mm: number;
  gap_mm: number;
  tempered_tolerance_mm: number;
  note_ru: string;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** Read-only projections for this exact dataset/plan/revision, never cached fixture answers. */
export function PlanInsights({ datasetId, planId, revision, materialNames = {} }: { datasetId: string; planId: string; revision: number; materialNames?: Record<string, string> }) {
  const { client } = useApi();
  const [open, setOpen] = useState(false);
  const path = `/plans/${encodeURIComponent(planId)}`;
  const query = { dataset_id: datasetId, revision };
  const validReference = (value: unknown): value is Record<string, unknown> => record(value)
    && value.dataset_id === datasetId && value.plan_id === planId && value.revision === revision
    && typeof value.inventory_version === 'string';
  const requirements = useQuery({
    queryKey: ['plan-new-requirements', datasetId, planId, revision],
    enabled: open,
    queryFn: ({ signal }) => client.get<NewRequirements>(`${path}/new-requirements`, {
      query, signal,
      validate: value => validReference(value) && Array.isArray(value.rows)
        && typeof value.is_active === 'boolean' && ['active', 'proposal', 'historical'].includes(String(value.scope))
        && typeof value.disclaimer_ru === 'string' && finite(value.total_quantity) && finite(value.total_area_mm2)
        && value.rows.every(row => record(row) && typeof row.material_id === 'string'
          && record(row.dimensions) && finite(row.dimensions.length_mm) && finite(row.dimensions.width_mm)
          && finite(row.quantity) && finite(row.area_mm2) && typeof row.reason_ru === 'string'
          && typeof row.reason_code === 'string' && Array.isArray(row.part_ids)
          && row.part_ids.every(id => typeof id === 'string')),
    }),
    refetchInterval: open ? 15_000 : false,
  });
  const margins = useQuery({
    queryKey: ['plan-geometry-margins', datasetId, planId, revision],
    enabled: open,
    queryFn: ({ signal }) => client.get<PlanMargins>(`${path}/geometry-margins`, {
      query, signal,
      validate: value => validReference(value) && Array.isArray(value.placements)
        && finite(value.trim_mm) && finite(value.gap_mm) && finite(value.tempered_tolerance_mm)
        && typeof value.note_ru === 'string'
        && value.placements.every(row => record(row) && typeof row.part_id === 'string'
          && typeof row.remnant_id === 'string' && typeof row.tempered === 'boolean'
          && ['cut_geometry', 'whole_piece_tolerance'].includes(String(row.margin_kind))
          && finite(row.minimum_excess_mm)
          && [row.edge_clearance_mm, row.neighbor_clearance_mm, row.dimension_deviation_mm]
            .every(number => number == null || finite(number))),
    }),
    refetchInterval: open ? 15_000 : false,
  });
  const newData = requirements.isError ? undefined : requirements.data;
  const marginData = margins.isError ? undefined : margins.data;

  return (
    <details className="details" onToggle={event => setOpen(event.currentTarget.open)}>
      <summary>Требуется новый материал и геометрический запас · версия {revision}</summary>
      {open && <div className="details-body">
        <div className="row">
          <Button busy={requirements.isFetching || margins.isFetching}
            onClick={() => { void requirements.refetch(); void margins.refetch(); }}>Обновить данные склада</Button>
        </div>
        <h3>Детали, для которых требуется новый материал</h3>
        {requirements.isPending && <LoadingState label="Проверяем потребность плана…" />}
        {requirements.isError && <ErrorState error={requirements.error} context="Неразмещённые детали"
          onRetry={() => { void requirements.refetch(); }} />}
        {newData && <>
          <StatusBadge tone={newData.is_active ? 'info' : 'neutral'}>
            {newData.is_active ? 'Потребность действующего плана'
              : newData.scope === 'historical' ? 'Историческая потребность' : 'Предложение плана, ещё не действует'}
          </StatusBadge>
          <p>Эти детали пока не размещены на остатках. Число новых листов и стоимость закупки не определены.</p>
          <p>Всего: {formatInt(newData.total_quantity)} деталей · {formatAreaM2(newData.total_area_mm2, 6)}.</p>
          {newData.rows.length === 0 ? <EmptyState title="Неразмещённых деталей нет" /> :
            <TableWrap label="Детали, для которых требуется новый материал" maxHeight={320}>
              <table><thead><tr><th>Материал</th><th>Размер</th><th>Количество</th><th>Площадь</th><th>Причина</th></tr></thead>
                <tbody>{newData.rows.map((row, index) => <tr key={`${row.material_id}-${index}`}>
                  <td>{materialNames[row.material_id] ?? 'Название материала не передано'}<details><summary>Служебный номер материала</summary>{row.material_id}</details></td><td>{formatDims(row.dimensions)}</td><td>{formatInt(row.quantity)}</td>
                  <td>{formatAreaM2(row.area_mm2, 6)}</td><td>{row.reason_ru}
                    <details><summary>Детали: {row.part_ids.length}</summary>{row.part_ids.join(', ')}</details>
                  </td>
                </tr>)}</tbody>
              </table>
            </TableWrap>}
        </>}
        <h3>Геометрический запас</h3>
        {margins.isPending && <LoadingState label="Проверяем размещения…" />}
        {margins.isError && <ErrorState error={margins.error} context="Геометрический запас"
          onRetry={() => { void margins.refetch(); }} />}
        {marginData && <>
          <p>{marginData.note_ru}</p>
          <p>Обычное стекло: край ≥{formatMm(marginData.trim_mm)}, зазор по разделяющей оси ≥{formatMm(marginData.gap_mm)}.
            {' '}Закалённое: только целый кусок, отклонение размера ±{formatMm(marginData.tempered_tolerance_mm)};
            край и зазор для резки к нему не применяются.</p>
          {marginData.placements.length === 0 ? <EmptyState title="Размещений на остатках нет" /> :
            <TableWrap label="Геометрический запас размещений" maxHeight={320}>
              <table><thead><tr><th>Деталь / кусок</th><th>Правило</th><th>Край</th><th>Зазор</th><th>Отклонение размера</th><th>Запас к допуску</th></tr></thead>
                <tbody>{marginData.placements.map(row => <tr key={row.part_id}>
                  <td>{row.part_id}<br /><small>{row.remnant_id}</small></td>
                  <td>{row.margin_kind === 'whole_piece_tolerance' ? 'Целое закалённое' : 'Обычный раскрой'}</td>
                  <td>{row.tempered ? 'Не применяется' : row.edge_clearance_mm == null ? '—' : formatMm(row.edge_clearance_mm)}</td>
                  <td>{row.tempered ? 'Не применяется' : row.neighbor_clearance_mm == null ? 'Нет соседа' : formatMm(row.neighbor_clearance_mm)}</td>
                  <td>{row.dimension_deviation_mm == null ? '—' : formatMm(row.dimension_deviation_mm)}</td>
                  <td>{formatMm(row.minimum_excess_mm)}</td>
                </tr>)}</tbody>
              </table>
            </TableWrap>}
        </>}
        {newData && marginData && newData.inventory_version !== marginData.inventory_version &&
          <p role="status">Склад изменился между проверками. Обновите данные перед сравнением таблиц.</p>}
      </div>}
    </details>
  );
}

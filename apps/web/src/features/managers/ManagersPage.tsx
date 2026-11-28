import { useQuery } from '@tanstack/react-query';
import { Filter } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useApi } from '../../api/context';
import type { ApplicationRow, Dataset, ManagerMetrics, MetricEvidence, Ratio } from '../../api/types';
import { formatInt, formatMoney, formatPercent } from '../../lib/format';
import { Button, EmptyState, ErrorState, LoadingState, Panel, SideDialog, TableWrap } from '../../ui/kit';
import { RequireDataset } from '../shell/RequireDataset';
import { ComparablePanel } from './ComparablePanel';

export function ManagersPage() {
  return <RequireDataset>{dataset => <Managers dataset={dataset} key={dataset.dataset_id} />}</RequireDataset>;
}

type MetricKey =
  | 'application_count'
  | 'mean_response_minutes'
  | 'conversion'
  | 'returns'
  | 'mean_sale_tg'
  | 'mean_application_tg'
  | 'complaints'
  | 'discounts';

const METRICS: { key: MetricKey; label: string; note: string }[] = [
  { key: 'application_count', label: 'Число заявок', note: 'строки applications после фильтра' },
  { key: 'mean_response_minutes', label: 'Среднее время ответа', note: 'задержка ответа клиенту, не трудозатраты' },
  { key: 'conversion', label: 'Конверсия', note: 'продано=1 / известные «продано»' },
  { key: 'returns', label: 'Доля возвратов', note: 'заявки с возвратом / все заявки менеджера (с известной меткой)' },
  { key: 'mean_sale_tg', label: 'Средний чек', note: 'по проданным заявкам (среднее сумма_тг при продано=1)' },
  { key: 'complaints', label: 'Доля жалоб', note: 'жалоба=1 / известные' },
  { key: 'discounts', label: 'Доля скидок', note: 'скидка=1 / известные' },
];

interface Filters {
  manager: string;
  product_group: string;
  channel: string;
  client_type: string;
  day_from: string;
  day_to: string;
}

const EMPTY: Filters = { manager: '', product_group: '', channel: '', client_type: '', day_from: '', day_to: '' };

/** Loads all application rows page by page (max 200 per page) for filter options and drill-down. */
function useAllApplications(datasetId: string) {
  const { api } = useApi();
  return useQuery({
    queryKey: ['applications-all', datasetId],
    staleTime: 5 * 60_000,
    queryFn: async ({ signal }) => {
      const rows: ApplicationRow[] = [];
      let offset = 0;
      for (let guard = 0; guard < 100; guard += 1) {
        const page = await api.applications(datasetId, { offset, limit: 200 }, signal);
        rows.push(...page.rows);
        offset += page.rows.length;
        if (!page.rows.length || offset >= page.total) break;
      }
      return rows;
    },
  });
}

function ratioText(ratio: Ratio): string {
  if (ratio.value === null || ratio.denominator === 0) return 'Нет фактических данных';
  return formatPercent(ratio.value);
}

function cell(metric: ManagerMetrics, key: MetricKey): { main: string; sub: string } {
  switch (key) {
    case 'application_count':
      return { main: formatInt(metric.application_count), sub: 'строк' };
    case 'mean_response_minutes':
      return {
        main: metric.mean_response_minutes === null ? 'Нет данных' : `${metric.mean_response_minutes.toFixed(1).replace('.', ',')} мин`,
        sub: metric.evidence?.mean_response_minutes ? `по ${metric.evidence.mean_response_minutes.denominator} известным` : '',
      };
    case 'mean_sale_tg':
      return { main: metric.mean_sale_tg === null ? 'Нет продаж' : formatMoney(metric.mean_sale_tg), sub: metric.evidence?.mean_sale_tg ? `${metric.evidence.mean_sale_tg.denominator} продаж` : '' };
    case 'mean_application_tg':
      return { main: metric.mean_application_tg === null ? 'Нет данных' : formatMoney(metric.mean_application_tg), sub: 'все заявки' };
    default: {
      const ratio = metric[key] as Ratio;
      return { main: ratioText(ratio), sub: `${ratio.numerator} / ${ratio.denominator}` };
    }
  }
}

function Managers({ dataset }: { dataset: Dataset }) {
  const { api } = useApi();
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [drill, setDrill] = useState<{ manager: ManagerMetrics; key: MetricKey } | null>(null);
  const all = useAllApplications(dataset.dataset_id);
  const query = useMemo(
    () => ({
      manager: filters.manager || undefined,
      product_group: filters.product_group || undefined,
      channel: filters.channel || undefined,
      client_type: filters.client_type || undefined,
      day_from: filters.day_from === '' ? undefined : Number(filters.day_from),
      day_to: filters.day_to === '' ? undefined : Number(filters.day_to),
    }),
    [filters],
  );
  const metrics = useQuery({
    queryKey: ['manager-metrics', dataset.dataset_id, query],
    queryFn: ({ signal }) => api.managerMetrics(dataset.dataset_id, query, signal),
  });
  const options = useMemo(() => {
    const collect = (field: string) => [...new Set((all.data ?? []).map(row => String(row[field] ?? '')).filter(Boolean))].sort();
    return { groups: collect('группа_товара'), channels: collect('канал'), types: collect('тип_клиента') };
  }, [all.data]);
  const rangeError = draft.day_from !== '' && draft.day_to !== '' && Number(draft.day_from) > Number(draft.day_to) ? 'Начало больше конца' : null;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Менеджеры · историческая аналитика</p>
          <h1>M1–M5: семь показателей с исходными строками</h1>
          <p className="lead">
            Каждый процент раскрывается числителем, знаменателем и строками. Отсутствие данных не равно нулю. Изменения склада, цен и прогнозов
            не меняют эту таблицу. Причинных выводов о влиянии менеджера нет.
          </p>
        </div>
      </header>
      <Panel title="Фильтры">
        <form
          className="filters"
          onSubmit={event => {
            event.preventDefault();
            if (!rangeError) setFilters(draft);
          }}
        >
          <label>
            Менеджер
            <select value={draft.manager} onChange={event => setDraft({ ...draft, manager: event.target.value })}>
              <option value="">Все</option>
              {['M1', 'M2', 'M3', 'M4', 'M5', 'unknown'].map(value => (
                <option key={value} value={value}>
                  {value === 'unknown' ? 'Неизвестный менеджер' : value}
                </option>
              ))}
            </select>
          </label>
          <label>
            Группа товара
            <select value={draft.product_group} onChange={event => setDraft({ ...draft, product_group: event.target.value })}>
              <option value="">Все</option>
              {options.groups.map(value => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            Канал
            <select value={draft.channel} onChange={event => setDraft({ ...draft, channel: event.target.value })}>
              <option value="">Все</option>
              {options.channels.map(value => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            Тип клиента
            <select value={draft.client_type} onChange={event => setDraft({ ...draft, client_type: event.target.value })}>
              <option value="">Все</option>
              {options.types.map(value => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            день_года с
            <input inputMode="numeric" value={draft.day_from} onChange={event => setDraft({ ...draft, day_from: event.target.value.replace(/\D/g, '') })} />
          </label>
          <label>
            по
            <input inputMode="numeric" value={draft.day_to} aria-invalid={rangeError ? true : undefined} onChange={event => setDraft({ ...draft, day_to: event.target.value.replace(/\D/g, '') })} />
          </label>
          <Button type="submit" variant="primary" icon={<Filter size={14} aria-hidden="true" />} disabled={Boolean(rangeError)}>
            Применить
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setDraft(EMPTY);
              setFilters(EMPTY);
            }}
          >
            Сбросить
          </Button>
          {rangeError && <small className="field-error">{rangeError}</small>}
        </form>
        <p className="small muted">день_года — исходное относительное значение учебной CRM, а не календарная дата.</p>
      </Panel>
      <ComparablePanel datasetId={dataset.dataset_id} />
      <Panel title="Показатели" subtitle="Нажмите на значение, чтобы открыть определение, знаменатель и исходные строки.">
        {metrics.isLoading && <LoadingState label="Считаем показатели…" />}
        {metrics.isError && <ErrorState error={metrics.error} onRetry={() => metrics.refetch()} context="M1–M5" />}
        {metrics.data && metrics.data.length === 0 && <EmptyState title="Нет строк для выбранных фильтров" />}
        {metrics.data && metrics.data.length > 0 && (
          <TableWrap label="Показатели менеджеров">
            <table className="table metrics-table">
              <thead>
                <tr>
                  <th scope="col">Менеджер</th>
                  {METRICS.map(metric => (
                    <th scope="col" key={metric.key} className="num" title={`${metric.label}: ${metric.note}`}>
                      {metric.label}
                      <small>{metric.note}</small>
                    </th>
                  ))}
                  <th scope="col" className="num">
                    Средняя сумма всех заявок<small>отдельный показатель, не средний чек</small>
                  </th>
                </tr>
              </thead>
              <tbody>
                {metrics.data.map(row => (
                  <tr key={row.manager}>
                    <th scope="row">
                      {row.manager === 'unknown' ? 'Неизвестный' : row.manager}
                      {row.source_manager_values && row.manager === 'unknown' && <div className="small muted">{row.source_manager_values.join(', ')}</div>}
                    </th>
                    {[...METRICS.map(metric => metric.key), 'mean_application_tg' as const].map(key => {
                      const value = cell(row, key);
                      return (
                        <td key={key} className="num">
                          <button className="metric-cell" onClick={() => setDrill({ manager: row, key })} aria-label={`${row.manager}: ${value.main}, открыть исходные строки`}>
                            <strong>{value.main}</strong>
                            {value.sub && <small>{value.sub}</small>}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Panel>
      {drill && <DrillDown drill={drill} rows={all.data} rowsState={all} onClose={() => setDrill(null)} />}
    </div>
  );
}

function DrillDown({
  drill,
  rows,
  rowsState,
  onClose,
}: {
  drill: { manager: ManagerMetrics; key: MetricKey };
  rows: ApplicationRow[] | undefined;
  rowsState: { isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown };
  onClose: () => void;
}) {
  const evidence: MetricEvidence | undefined = drill.manager.evidence?.[drill.key];
  const label = [...METRICS, { key: 'mean_application_tg', label: 'Средняя сумма всех заявок', note: '' }].find(item => item.key === drill.key)?.label;
  const known = new Set(evidence?.known_app_ids ?? []);
  const selected = (rows ?? []).filter(row => (evidence?.source_app_ids ?? []).includes(row.app_id));
  return (
    <SideDialog open onOpenChange={open => !open && onClose()} title={`${drill.manager.manager} · ${label}`} wide>
      {!evidence ? (
        <EmptyState title="Сервер не передал происхождение показателя" />
      ) : (
        <div className="stack">
          <dl className="kv">
            <div className="kv-row">
              <dt>Определение</dt>
              <dd>{evidence.definition}</dd>
            </div>
            <div className="kv-row">
              <dt>Числитель</dt>
              <dd className="mono">{evidence.numerator ?? 'нет'}</dd>
            </div>
            <div className="kv-row">
              <dt>Знаменатель (известные значения)</dt>
              <dd className="mono">{evidence.denominator}</dd>
            </div>
            <div className="kv-row">
              <dt>Всего строк после фильтра</dt>
              <dd className="mono">{evidence.total}</dd>
            </div>
            <div className="kv-row">
              <dt>Полнота</dt>
              <dd>{evidence.completeness === null ? 'нет строк' : formatPercent(evidence.completeness)}</dd>
            </div>
          </dl>
          {rowsState.isLoading && <LoadingState label="Загружаем исходные строки…" />}
          {rowsState.isError && <ErrorState error={rowsState.error} onRetry={() => rowsState.refetch()} />}
          {rows && (
            <TableWrap label="Исходные строки показателя" maxHeight={480}>
              <table className="table compact">
                <thead>
                  <tr>
                    <th scope="col">строка</th>
                    <th scope="col">Заявка</th>
                    <th scope="col">Клиент</th>
                    <th scope="col">группа</th>
                    <th scope="col">канал</th>
                    <th scope="col" className="num">
                      сумма_тг
                    </th>
                    <th scope="col">продано</th>
                    <th scope="col">вернулся</th>
                    <th scope="col">жалоба</th>
                    <th scope="col">скидка</th>
                    <th scope="col" className="num">
                      ответ, мин
                    </th>
                    <th scope="col">в знаменателе</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.map(row => (
                    <tr key={row.app_id}>
                      <td className="num">{row.source_row}</td>
                      <td className="mono">{row.app_id}</td>
                      <td className="mono">{row.client_id}</td>
                      <td>{show(row['группа_товара'])}</td>
                      <td>{show(row['канал'])}</td>
                      <td className="num">{row['сумма_тг'] === null || row['сумма_тг'] === undefined ? <em className="muted">нет</em> : formatMoney(String(row['сумма_тг']), { currency: false })}</td>
                      <td>{show(row['продано'])}</td>
                      <td>{show(row['вернулся_за_60_дней'])}</td>
                      <td>{show(row['жалоба'])}</td>
                      <td>{show(row['скидка'])}</td>
                      <td className="num">{show(row['ответ_через_мин'])}</td>
                      <td>{known.has(row.app_id) ? 'да' : <em className="muted">нет (значение неизвестно)</em>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
        </div>
      )}
    </SideDialog>
  );
}

function show(value: unknown) {
  return value === null || value === undefined || value === '' ? <em className="muted">нет</em> : String(value);
}

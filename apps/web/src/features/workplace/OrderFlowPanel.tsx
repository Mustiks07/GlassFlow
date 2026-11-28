import { useEffect, useState } from 'react';
import { OperationalDocument } from './OperationalDocument';
import { useQuery } from '@tanstack/react-query';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import { newIdempotencyKey } from '../../api/client';
import type { Dataset, Quote } from '../../api/types';
import { Button, ErrorState, Panel } from '../../ui/kit';
import { formatMoney } from '../../lib/format';
import { useRoute } from '../../state/router';

type Sheet = components['schemas']['OrderSheet'];
type Part = components['schemas']['Part'];
type Placement = components['schemas']['Placement'];
export const flowLabel = (state?: string) => ({ draft: 'Черновик', needs_review: 'Нужно уточнение',
  ready: 'Проверено', confirmed: 'Подтверждено', reserved: 'В резерве', checked: 'Склад проверен',
  handed_over: 'Передано в работу', completed: 'Расход подтвержден', stale: 'Нужна перепроверка',
  cancelled: 'Отменено', open: 'Открыт', missing: 'Нет расчета', unchecked: 'Не проверен',
} as Record<string, string>)[state ?? ''] ?? 'Состояние не определено';

export function ActualUse({ dataset, subject, kind, onDone }: {
  dataset: Dataset; subject: { version?: number; order_id?: string; basket_id?: string };
  kind: 'order' | 'basket'; onDone: () => void;
}) {
  const { client } = useApi();
  const [template, setTemplate] = useState<{ parts: Part[]; placements: Placement[] } | null>(null);
  const [checked, setChecked] = useState(false);
  const [note, setNote] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [key] = useState(newIdempotencyKey);
  const [execution, setExecution] = useState<{ execution_ref: string; execution_version: number } | null>(null);
  const body = { dataset_id: dataset.dataset_id, subject_type: kind, subject_id: subject.order_id ?? subject.basket_id,
    expected_version: subject.version, execution_ref: 'new', execution_version: 1,
    operator: 'local-manager', note, discrepancy_reason: note };
  async function prepare() {
    setBusy(true); setError(null);
    try { const value = await client.post<{ parts: Part[]; placements: Placement[] }>('/cutting/execution-template', body);
      setTemplate({ parts: value.parts, placements: value.placements }); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function confirm() {
    if (!template || !checked || !note.trim()) return;
    setBusy(true); setError(null);
    try {
      const recorded = execution ?? await client.post<{ execution_ref: string; execution_version: number }>('/cutting/executions',
        { ...body, ...template }, { idempotencyKey: `${key}:execution` });
      const ref = { execution_ref: recorded.execution_ref, execution_version: recorded.execution_version };
      setExecution(ref);
      await client.post('/material-use', { ...body, ...ref }, { idempotencyKey: `${key}:use` });
      onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <section className="stack" aria-label="Фактическое исполнение">
    <Button onClick={prepare} busy={busy}>Проверить фактическое исполнение</Button>
    {template && <>
      <p className="small">Показано плановое размещение. Сверьте каждую деталь с фактическим результатом и исправьте размеры при расхождении.</p>
      {template.parts.map((part, index) => <div className="row wrap" key={part.part_id}>
        <span>{part.part_id} · {part.material_id}</span>
        <label>Фактическая длина, мм <input type="number" min="1" value={part.dimensions.length_mm} onChange={e => {
          const parts = structuredClone(template.parts); parts[index].dimensions.length_mm = Number(e.target.value);
          setTemplate({ ...template, parts }); setChecked(false);
        }} /></label>
        <label>Фактическая ширина, мм <input type="number" min="1" value={part.dimensions.width_mm} onChange={e => {
          const parts = structuredClone(template.parts); parts[index].dimensions.width_mm = Number(e.target.value);
          setTemplate({ ...template, parts }); setChecked(false);
        }} /></label>
        <span>{template.placements[index]?.remnant_id} · x={template.placements[index]?.x_mm}, y={template.placements[index]?.y_mm}</span>
      </div>)}
      <label>Результат проверки / причина расхождения <input value={note} onChange={e => setNote(e.target.value)} /></label>
      <label><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} /> Я сверил фактические детали и подтверждаю расход материала</label>
      <Button variant="primary" busy={busy} disabled={!checked || !note.trim()} onClick={confirm}>Подтвердить фактический расход один раз</Button>
    </>}
    {error != null && <ErrorState error={error} />}
  </section>;
}

export function OrderFlowPanel({ dataset, quote }: { dataset: Dataset; quote: Quote | null }) {
  const { client } = useApi();
  const targetId = useRoute().params.get('order_id');
  const [selected, setSelected] = useState<Sheet | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [remnant, setRemnant] = useState('');
  const [retryKey, setRetryKey] = useState(newIdempotencyKey);
  const list = useQuery({ queryKey: ['order-sheets', dataset.dataset_id],
    queryFn: () => client.get<Sheet[]>('/order-sheets', { query: { dataset_id: dataset.dataset_id } }) });
  useEffect(() => {
    let current = true;
    if (targetId) client.get<Sheet>(`/order-sheets/${encodeURIComponent(targetId)}`, { query: { dataset_id: dataset.dataset_id } })
      .then(value => { if (current) { setSelected(value); setRemnant(value.facts?.remnant.remnant_id ?? ''); setError(null); } })
      .catch(e => { if (current) setError(e); });
    return () => { current = false; };
  }, [client, dataset.dataset_id, targetId]);
  async function create() {
    if (!quote?.customer_id) return;
    setBusy(true); setError(null);
    try {
      const sheet = await client.post<Sheet>('/order-sheets', { dataset_id: dataset.dataset_id,
        customer_ref: quote.customer_id, request_text: quote.product_name ?? 'Заявка из расчета' }, { idempotencyKey: retryKey });
      setSelected(sheet); setRemnant(quote.candidate_refs?.[0]?.remnant_id ?? '');
      setRetryKey(newIdempotencyKey()); await list.refetch();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function command(operation: string) {
    if (!selected) return;
    setBusy(true); setError(null);
    try {
      let extra = {};
      if (operation === 'bind' && quote) {
        const piece = await client.get<{ version: number }>(`/remnants/${encodeURIComponent(remnant)}`, { query: { dataset_id: dataset.dataset_id } });
        extra = { quote_id: quote.quote_id, quote_revision: quote.revision, remnant_id: remnant, remnant_version: piece.version };
      }
      const result = await client.post<Sheet>(`/order-sheets/${selected.order_id}/${operation}`,
        { dataset_id: dataset.dataset_id, expected_version: selected.version, operator: 'local-manager', note, ...extra },
        { idempotencyKey: `${retryKey}:${operation}` });
      setSelected(result); setRetryKey(newIdempotencyKey()); await list.refetch();
    } catch (e) { setError(e); await list.refetch(); } finally { setBusy(false); }
  }
  return <Panel title="Предложение и задание складу" subtitle="Подтверждение, резерв, личная проверка, передача и фактический расход — отдельные действия.">
    <div className="stack">
      {dataset.mode !== 'workspace' ? <p>Откройте рабочую копию для операций заказа.</p> : <>
        <Button onClick={create} busy={busy} disabled={!quote?.customer_id || quote.status !== 'confirmed'}>Создать лист из подтвержденного расчета</Button>
        {!quote?.customer_id && <p className="small muted">Сначала укажите заказчика в расчете. Анонимный расчет не назначается клиенту автоматически.</p>}
        <label>Сохраненные заказы <select value={selected?.order_id ?? ''} onChange={e => setSelected(list.data?.find(s => s.order_id === e.target.value) ?? null)}>
          <option value="">Выберите заказ</option>{list.data?.map(s => <option key={s.order_id} value={s.order_id}>{s.customer_ref} · {flowLabel(s.quote_state)} · {flowLabel(s.lifecycle)}</option>)}
        </select></label>
      </>}
      {selected && <>
        <p>Клиент: {selected.customer_ref} · версия {selected.version} · {flowLabel(selected.quote_state)} / {flowLabel(selected.warehouse_state)} / {flowLabel(selected.lifecycle)}</p>
        {selected.stale_reason && <p role="alert">{selected.stale_reason}</p>}
        {selected.offer && <div className="metric"><span>Предложение клиенту</span><strong>{formatMoney(selected.offer.quote.total_tg)}</strong><span>{selected.offer.quote.product_name}</span></div>}
        {selected.warehouse_task && <div><strong>Задание складу</strong><p>{selected.warehouse_task.remnant.remnant_id} · {selected.warehouse_task.remnant.location_raw} · {selected.warehouse_task.requested_dimensions.length_mm}×{selected.warehouse_task.requested_dimensions.width_mm} мм · {selected.warehouse_task.quantity} шт.</p></div>}
        {selected.lifecycle === 'open' && <>
          <label>Кусок для нового расчета <input value={remnant} onChange={e => setRemnant(e.target.value)} /></label>
          <Button onClick={() => command('bind')} busy={busy} disabled={!quote || !remnant || quote.status !== 'confirmed'}>Привязать текущий расчет и кусок</Button>
          <label>Заметка личной проверки <input value={note} onChange={e => setNote(e.target.value)} /></label>
          <div className="row wrap">
            <Button onClick={() => command('confirm')} busy={busy} disabled={selected.quote_state !== 'draft'}>Подтвердить предложение</Button>
            <Button onClick={() => command('reserve')} busy={busy} disabled={selected.quote_state !== 'confirmed' || selected.reservation?.state === 'active'}>Резерв для заказа</Button>
            <Button onClick={() => command('warehouse-check')} busy={busy} disabled={!note.trim() || selected.reservation?.state !== 'active'}>Склад проверен лично</Button>
            <Button onClick={() => command('handover')} busy={busy} disabled={selected.warehouse_state !== 'checked'}>Передать в работу</Button>
            <Button onClick={() => command('release')} busy={busy} disabled={selected.reservation?.state !== 'active'}>Снять резерв заказа</Button>
            <Button onClick={() => command('cancel')} busy={busy}>Отменить заказ</Button>
          </div>
        </>}
        {selected.lifecycle === 'handed_over' && <ActualUse dataset={dataset} subject={selected} kind="order" onDone={async () => {
          setSelected(await client.get<Sheet>(`/order-sheets/${selected.order_id}`, { query: { dataset_id: dataset.dataset_id } })); await list.refetch();
        }} />}
        {selected.material_use_id && <p role="status">Фактический расход записан: {selected.material_use_id}. Повторного списания нет.</p>}
        {dataset.mode === 'workspace' && selected.quote_state === 'confirmed' && selected.lifecycle !== 'completed' && selected.lifecycle !== 'cancelled' && selected.version != null && <OperationalDocument datasetId={dataset.dataset_id} kind="order" subjectId={selected.order_id} version={selected.version} />}
      </>}
      {error != null && <ErrorState error={error} />}
    </div>
  </Panel>;
}

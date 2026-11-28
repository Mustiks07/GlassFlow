import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import { newIdempotencyKey } from '../../api/client';
import type { Dataset, Job } from '../../api/types';
import { Button, ErrorState, Panel } from '../../ui/kit';
import { formatMoney } from '../../lib/format';
import { ActualUse, flowLabel } from './OrderFlowPanel';
import { useRoute } from '../../state/router';
import { OperationalDocument } from './OperationalDocument';

type Basket = components['schemas']['Basket'];
type Line = components['schemas']['BasketLineDraft'];
type Quote = components['schemas']['Quote'];

export function BasketPanel({ dataset }: { dataset: Dataset }) {
  const { client, api } = useApi();
  const targetId = useRoute().params.get('basket_id');
  const [customer, setCustomer] = useState('');
  const [text, setText] = useState('');
  const [basket, setBasket] = useState<Basket | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [retryKey, setRetryKey] = useState(newIdempotencyKey);
  const list = useQuery({ queryKey: ['baskets', dataset.dataset_id], queryFn: () => client.get<Basket[]>('/baskets', { query: { dataset_id: dataset.dataset_id } }) });
  const catalog = useQuery({ queryKey: ['catalog-baskets', dataset.dataset_id], queryFn: () => api.listCatalog(dataset.dataset_id, dataset.kb_version ?? "") });
  useEffect(() => {
    let current = true;
    if (targetId) client.get<Basket>(`/baskets/${encodeURIComponent(targetId)}`, { query: { dataset_id: dataset.dataset_id } })
      .then(value => { if (current) { setBasket(value); setLines(value.lines ?? []); setCustomer(value.customer_ref); setError(null); } })
      .catch(e => { if (current) setError(e); });
    return () => { current = false; };
  }, [client, dataset.dataset_id, targetId]);
  async function wait(job: Job) {
    for (let n = 0; n < 300; n++) {
      const value = await api.getJob(job.job_id);
      setStage(value.stage);
      if (value.state === 'completed') return value.result as Record<string, unknown>;
      if (!['queued', 'running'].includes(value.state)) throw new Error(`Задание ${value.state}: ${value.error_code ?? ''}`);
      await new Promise(resolve => setTimeout(resolve, 300));
    }
    throw new Error('Расчет продолжается. Откройте сохраненную корзину и проверьте задания.');
  }
  async function run(operation: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await operation(); setRetryKey(newIdempotencyKey()); await list.refetch(); }
    catch (e) { setError(e); } finally { setBusy(false); setStage(''); }
  }
  const actionBody = (value: Basket) => ({ dataset_id: dataset.dataset_id, expected_version: value.version, operator: 'local-manager', note });
  async function parse() {
    let value = basket;
    if (!value) value = await client.post<Basket>('/baskets', { dataset_id: dataset.dataset_id, customer_ref: customer, request_text: text }, { idempotencyKey: `${retryKey}:create` });
    setBasket(value);
    const job = await client.post<Job>(`/baskets/${value.basket_id}/parse`, actionBody(value), { idempotencyKey: `${retryKey}:parse` });
    await wait(job);
    value = await client.post<Basket>(`/baskets/${value.basket_id}/apply-parse`, { ...actionBody(value), job_id: job.job_id }, { idempotencyKey: `${retryKey}:apply` });
    setBasket(value); setLines(value.lines ?? []);
  }
  async function calculate() {
    if (!basket || !note.trim()) return;
    const reviewed = lines.map(line => ({ ...line, clarification: line.request ? null : line.clarification }));
    let value = await client.post<Basket>(`/baskets/${basket.basket_id}/lines`, { ...actionBody(basket), lines: reviewed }, { idempotencyKey: `${retryKey}:lines` });
    setBasket(value); setLines(value.lines ?? []);
    const refs: { line_id: string; quote_id?: string; quote_revision?: number }[] = [];
    let hasGlass = false;
    for (const line of reviewed) {
      if (!line.request) { refs.push({ line_id: line.line_id }); continue; }
      setStage(`Расчет: ${line.text}`);
      let quote = await client.post<Quote>('/quotes', line.request);
      if (quote.status === 'calculated' && quote.total_tg != null) {
        quote = await client.post<Quote>(`/quotes/${quote.quote_id}/confirm`, { dataset_id: dataset.dataset_id,
          expected_revision: quote.revision, confirmed_by: 'local-manager' }, { idempotencyKey: `${retryKey}:quote:${line.line_id}` });
      }
      hasGlass ||= Boolean(quote.material_id);
      refs.push({ line_id: line.line_id, quote_id: quote.quote_id, quote_revision: quote.revision });
    }
    let binding: Record<string, unknown> = { ...actionBody(value), lines: refs };
    if (hasGlass && refs.every(r => r.quote_id)) {
      const job = await client.post<Job>(`/baskets/${value.basket_id}/selection`, binding, { idempotencyKey: `${retryKey}:selection` });
      const selected = await wait(job);
      binding = { ...binding, selection_ref: selected.selection_ref, selection_version: selected.selection_version };
    }
    value = await client.post<Basket>(`/baskets/${value.basket_id}/bind`, binding, { idempotencyKey: `${retryKey}:bind` });
    setBasket(value);
  }
  function update(index: number, key: 'product' | 'length' | 'width' | 'quantity', raw: string) {
    const copy = structuredClone(lines);
    const request = copy[index].request ?? { dataset_id: dataset.dataset_id, catalog_product_id: '', kb_version: dataset.kb_version ?? '', customer_id: basket?.customer_ref ?? customer, quantity: 1 };
    if (key === 'product') request.catalog_product_id = raw;
    else if (key === 'quantity') request.quantity = Number(raw);
    else request.dimensions = { length_mm: request.dimensions?.length_mm ?? 0, width_mm: request.dimensions?.width_mm ?? 0, [key === 'length' ? 'length_mm' : 'width_mm']: Number(raw) };
    copy[index].request = request;
    setLines(copy);
  }
  async function command(operation: string) {
    if (!basket) return;
    setBasket(await client.post<Basket>(`/baskets/${basket.basket_id}/${operation}`, actionBody(basket), { idempotencyKey: `${retryKey}:${operation}` }));
  }
  return <Panel title="Корзина заявки" subtitle="Каждую позицию можно уточнить. Итог всей корзины неизвестен, пока не проверены все строки.">
    <div className="stack">
      {dataset.mode !== 'workspace' ? <p>Для корзины откройте рабочую копию.</p> : <>
        <label>Сохраненная корзина <select value={basket?.basket_id ?? ''} onChange={e => {
          const value = list.data?.find(v => v.basket_id === e.target.value) ?? null; setBasket(value); setLines(value?.lines ?? []); setRetryKey(newIdempotencyKey());
        }}><option value="">Новая заявка</option>{list.data?.map(v => <option key={v.basket_id} value={v.basket_id}>{v.customer_ref} · {flowLabel(v.state)} · {v.request_text.slice(0, 45)}</option>)}</select></label>
        {!basket && <>
          <label>Заказчик корзины <input value={customer} onChange={e => setCustomer(e.target.value)} /></label>
          <label>Позиции заявки, каждая с новой строки <textarea rows={4} value={text} onChange={e => setText(e.target.value)} placeholder="2 детали стекло прозрачное 6 мм 450×370 мм с кромкой по всем сторонам; 3 шт AB1001" /></label>
          <Button busy={busy} disabled={!customer.trim() || !text.trim()} onClick={() => run(parse)}>Разобрать все позиции</Button>
        </>}
        {basket && <>
          <p>Клиент {basket.customer_ref} · {flowLabel(basket.state)} · версия {basket.version}</p>
          {basket.state === 'draft' || basket.state === 'needs_review' || basket.state === 'ready' || basket.state === 'stale' ? <>
            {lines.map((line, index) => <fieldset className="stack" key={line.line_id}><legend>{line.text}</legend>
              {line.clarification && <p role="status">Уточнение: {line.clarification}</p>}
              <label>Товар позиции {index + 1}<select value={line.request?.catalog_product_id ?? ''} onChange={e => update(index, 'product', e.target.value)}><option value="">Требуется уточнение</option>{catalog.data?.map(p => <option key={p.catalog_product_id} value={p.catalog_product_id}>{p.name}</option>)}</select></label>
              <div className="row wrap">{(['length', 'width', 'quantity'] as const).map(key => <label key={key}>{key === 'length' ? 'Длина, мм' : key === 'width' ? 'Ширина, мм' : 'Количество'}
                <input type="number" min="1" value={key === 'quantity' ? line.request?.quantity ?? '' : key === 'length' ? line.request?.dimensions?.length_mm ?? '' : line.request?.dimensions?.width_mm ?? ''} onChange={e => update(index, key, e.target.value)} /></label>)}</div>
            </fieldset>)}
          </> : null}
          <label>Заметка проверки всех позиций <input value={note} onChange={e => setNote(e.target.value)} /></label>
          {['draft', 'needs_review', 'ready', 'stale'].includes(basket.state ?? "") && <Button busy={busy} disabled={!note.trim() || !lines.length} onClick={() => run(calculate)}>Проверил строки — рассчитать и подобрать совместно</Button>}
          <div className="metric"><span>Итог всей корзины</span><strong>{basket.total_tg == null ? 'Требуется уточнение' : formatMoney(basket.total_tg)}</strong></div>
          {basket.total_tg == null && basket.known_subtotal_tg && <p>Известная часть: {formatMoney(basket.known_subtotal_tg)}. Это не сумма заказа.</p>}
          {basket.issues?.map(issue => <p role="status" key={issue}>{issue.startsWith('line:') ? 'Уточните параметры, цену или совместимость указанной позиции.' : issue === 'joint_stock_validation_required' ? 'Требуется совместная проверка размещения всех стеклянных позиций.' : issue}</p>)}
          <div className="row wrap">{([
            ['confirm', 'Подтвердить всю корзину', basket.state === 'ready'],
            ['reserve', 'Резерв всей корзины', basket.state === 'confirmed'],
            ['warehouse-check', 'Все позиции проверены на складе', basket.state === 'reserved' && Boolean(note.trim())],
            ['handover', 'Передать корзину в работу', basket.state === 'checked'],
            ['release', 'Снять весь резерв', basket.reservation?.state === 'active' && basket.state !== 'handed_over'],
            ['cancel', 'Отменить корзину', !['completed', 'handed_over', 'cancelled'].includes(basket.state ?? "")],
          ] as const).map(([operation, label, enabled]) => <Button key={operation} busy={busy} disabled={!enabled} onClick={() => run(() => command(operation))}>{label}</Button>)}</div>
          {basket.state === 'handed_over' && <ActualUse dataset={dataset} subject={basket} kind="basket" onDone={async () => { setBasket(await client.get<Basket>(`/baskets/${basket.basket_id}`, { query: { dataset_id: dataset.dataset_id } })); await list.refetch(); }} />}
          {basket.material_use_id && <p role="status">Фактический расход сохранен: {basket.material_use_id}</p>}
          {dataset.mode === 'workspace' && basket.state && basket.version != null && ['confirmed', 'reserved', 'checked', 'handed_over'].includes(basket.state) && <OperationalDocument datasetId={dataset.dataset_id} kind="basket" subjectId={basket.basket_id} version={basket.version} />}
        </>}
        {stage && <p role="status">{stage}</p>}
        {error != null && <ErrorState error={error} />}
      </>}
    </div>
  </Panel>;
}

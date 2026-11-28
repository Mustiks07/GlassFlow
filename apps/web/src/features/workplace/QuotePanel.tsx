import { useMutation, useQuery } from '@tanstack/react-query';
import { Calculator, RefreshCw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import { asApiError } from '../../api/errors';
import type { CatalogProduct, Dataset, Processing, Quote, QuoteRequest } from '../../api/types';
import { formatDims, formatMoney } from '../../lib/format';
import { describeConversion, parseLength } from '../../lib/units';
import { useAppStore, useQuoteDraft, type QuoteDraft } from '../../state/store';
import { Button, Details, ErrorState, Field, LoadingState, Panel, StaleNotice, StatusBadge, TableWrap } from '../../ui/kit';
import { kbVersionOf } from '../shell/dataset';
import { EvidenceList } from './EvidenceList';

const PRICE_TYPE: Record<string, string> = {
  per_m2: 'за м²',
  per_sheet: 'за лист',
  retail_unit: 'розница, шт',
  bulk_unit: 'опт, шт',
  per_m: 'за пог. м',
};

const MAPPING_LABEL: Record<Quote['material_mapping_status'], string> = {
  confirmed: 'Складской материал подтвержден',
  proposed: 'Соответствие предложено, но не подтверждено менеджером',
  unmapped: 'Нет подтвержденного соответствия складу (это не «нет в наличии» и не NEW)',
  ambiguous: 'Соответствие неоднозначно — нужен выбор менеджера',
};

const STATUS_LABEL: Record<Quote['status'], string> = {
  calculated: 'Рассчитано',
  needs_review: 'Нужна проверка менеджера',
  ready: 'Готово к подтверждению',
  confirmed: 'Подтверждено',
  superseded: 'Заменено новой ревизией',
  cancelled: 'Отменено',
};

interface FormState {
  request: QuoteRequest | null;
  errors: Partial<Record<'catalogProductId' | 'length' | 'width' | 'quantity' | 'sides', string>>;
  notes: string[];
}

/** Turns the draft into a validated request. No commercial arithmetic happens here. */
export function buildRequest(draft: QuoteDraft, datasetId: string, kbVersion: string | null): FormState {
  const errors: FormState['errors'] = {};
  const notes: string[] = [];
  if (!draft.catalogProductId) errors.catalogProductId = 'Выберите товар каталога';
  let dimensions: QuoteRequest['dimensions'] = null;
  if (draft.length.trim() || draft.width.trim()) {
    const length = parseLength(draft.length);
    const width = parseLength(draft.width);
    if (!length.ok) errors.length = length.reason;
    if (!width.ok) errors.width = width.reason;
    if (length.ok && width.ok) {
      dimensions = { length_mm: length.mm, width_mm: width.mm };
      for (const parsed of [length, width]) {
        const note = describeConversion(parsed);
        if (note) notes.push(note);
      }
    }
  }
  const quantity = draft.quantity.trim();
  if (!/^\d+$/.test(quantity) || Number(quantity) < 1) errors.quantity = 'Количество — целое число от 1';
  if (draft.processing !== 'none' && draft.sides === 'selected' && draft.selectedSides.length === 0)
    errors.sides = 'Отметьте обрабатываемые стороны';
  if (Object.keys(errors).length || !kbVersion) return { request: null, errors, notes };
  const processing: Processing = {
    kind: draft.processing,
    sides: draft.sides,
    selected_sides: draft.sides === 'selected' ? draft.selectedSides : [],
  };
  return {
    request: {
      dataset_id: datasetId,
      catalog_product_id: draft.catalogProductId,
      dimensions,
      quantity: Number(quantity),
      processing,
      kb_version: kbVersion,
      customer_id: draft.customerId.trim() || null,
      inventory_mode: 'free_whole_remnants',
    },
    errors,
    notes,
  };
}

function sameInputs(quote: Quote, request: QuoteRequest | null): boolean {
  if (!request) return false;
  if (quote.catalog_product_id !== undefined && quote.catalog_product_id !== request.catalog_product_id) return false;
  if (quote.quantity !== undefined && quote.quantity !== request.quantity) return false;
  if (quote.dimensions !== undefined) {
    const a = quote.dimensions;
    const b = request.dimensions ?? null;
    if ((a === null) !== (b === null)) return false;
    if (a && b && (a.length_mm !== b.length_mm || a.width_mm !== b.width_mm)) return false;
  }
  return true;
}

export function QuotePanel({
  dataset,
  quote,
  onQuote,
  onStaleChange,
}: {
  dataset: Dataset;
  quote: Quote | null;
  onQuote: (quote: Quote | null) => void;
  onStaleChange: (stale: boolean) => void;
}) {
  const { api } = useApi();
  const draft = useQuoteDraft(dataset.dataset_id);
  const updateDraft = useAppStore(state => state.updateQuoteDraft);
  const kbVersion = kbVersionOf(dataset);
  const [touched, setTouched] = useState(false);
  const [reviseKey, setReviseKey] = useState(newIdempotencyKey);
  const [search, setSearch] = useState('');
  /** Request that produced the shown quote; any difference marks the quote stale. */
  const [basis, setBasis] = useState<string | null>(null);

  const catalog = useQuery({
    queryKey: ['catalog', dataset.dataset_id, kbVersion],
    enabled: Boolean(kbVersion),
    queryFn: ({ signal }) => api.listCatalog(dataset.dataset_id, kbVersion as string, signal),
    staleTime: 60_000,
  });

  // Restore the last quote after refresh.
  const restored = useQuery({
    queryKey: ['quote', dataset.dataset_id, draft.quoteId],
    enabled: Boolean(draft.quoteId) && !quote,
    queryFn: ({ signal }) => api.getQuote(draft.quoteId as string, dataset.dataset_id, signal),
    retry: false,
  });
  useEffect(() => {
    if (restored.data && !quote) onQuote(restored.data);
  }, [restored.data, quote, onQuote]);

  const form = useMemo(() => buildRequest(draft, dataset.dataset_id, kbVersion), [draft, dataset.dataset_id, kbVersion]);
  const stale =
    Boolean(quote && ((basis !== null && basis !== JSON.stringify(form.request)) || !sameInputs(quote, form.request))) ||
    Boolean(quote?.stale);
  useEffect(() => onStaleChange(stale), [stale, onStaleChange]);

  const calculate = useMutation({
    mutationFn: async (request: QuoteRequest) => {
      if (quote && quote.status !== 'confirmed') {
        // Changing inputs creates a new revision of the same quote (expected_revision guards races).
        return api.reviseQuote(
          quote.quote_id,
          {
            dataset_id: dataset.dataset_id,
            expected_revision: quote.revision,
            changes: {
              catalog_product_id: request.catalog_product_id,
              dimensions: request.dimensions,
              quantity: request.quantity,
              processing: request.processing,
              customer_id: request.customer_id,
              kb_version: request.kb_version,
            },
          },
          reviseKey,
        );
      }
      return api.calculateQuote(request);
    },
    onSuccess: (result, request) => {
      setBasis(JSON.stringify(request));
      onQuote(result);
      setReviseKey(newIdempotencyKey());
      updateDraft(dataset.dataset_id, { quoteId: result.quote_id });
    },
  });

  const products = catalog.data ?? [];
  const filtered = search.trim()
    ? products.filter(product => `${product.name} ${product.catalog_product_id} ${product.category}`.toLowerCase().includes(search.trim().toLowerCase()))
    : products;
  const selected = products.find(product => product.catalog_product_id === draft.catalogProductId);
  const show = (name: keyof FormState['errors']) => (touched ? form.errors[name] : undefined);
  const serverField = (name: string) => (calculate.error ? asApiError(calculate.error).fieldMessage(name) : undefined);
  const update = (patch: Partial<QuoteDraft>) => updateDraft(dataset.dataset_id, patch);

  return (
    <Panel title="Параметры и расчет" subtitle="Размеры в мм по умолчанию; см и м пересчитываются с показом исходного значения. Итог считает сервер.">
      <form
        className="stack"
        onSubmit={event => {
          event.preventDefault();
          setTouched(true);
          if (form.request) calculate.mutate(form.request);
        }}
        noValidate
      >
        <div className="form-grid">
          <Field label="Поиск по каталогу" hint={catalog.data ? `${products.length} позиций из действующей базы знаний` : undefined}>
            {props => <input {...props} type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="стекло 6 мм, зеркало, уголок…" />}
          </Field>
          <Field label="Товар каталога" required error={show('catalogProductId') ?? serverField('catalog_product_id')}>
            {props => (
              <select {...props} value={draft.catalogProductId} onChange={event => update({ catalogProductId: event.target.value })} disabled={!catalog.data}>
                <option value="">{catalog.isLoading ? 'Загрузка каталога…' : 'Выберите позицию'}</option>
                {selected && !filtered.includes(selected) && <option value={selected.catalog_product_id}>{selected.name}</option>}
                {filtered.slice(0, 300).map(product => (
                  <option key={product.catalog_product_id} value={product.catalog_product_id}>
                    {product.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </div>
        {catalog.isError && <ErrorState error={catalog.error} onRetry={() => catalog.refetch()} context="Каталог" />}
        {selected && <ProductPrices product={selected} />}
        <div className="form-grid four">
          <Field label="Длина" hint={hintFor(draft.length)} error={show('length') ?? serverField('length_mm')}>
            {props => <input {...props} value={draft.length} inputMode="decimal" placeholder="мм" onChange={event => update({ length: event.target.value })} />}
          </Field>
          <Field label="Ширина" hint={hintFor(draft.width)} error={show('width') ?? serverField('width_mm')}>
            {props => <input {...props} value={draft.width} inputMode="decimal" placeholder="мм" onChange={event => update({ width: event.target.value })} />}
          </Field>
          <Field label="Количество, шт" required error={show('quantity') ?? serverField('quantity')}>
            {props => <input {...props} value={draft.quantity} inputMode="numeric" onChange={event => update({ quantity: event.target.value })} />}
          </Field>
          <Field label="Обработка">
            {props => (
              <select {...props} value={draft.processing} onChange={event => update({ processing: event.target.value as QuoteDraft['processing'] })}>
                <option value="none">Без обработки</option>
                <option value="euro_edge">Евро-кромка</option>
                <option value="facet">Фацет</option>
                <option value="sandblast">Пескоструй</option>
              </select>
            )}
          </Field>
        </div>
        {draft.processing !== 'none' && (
          <fieldset className="fieldset">
            <legend>Обрабатываемые стороны</legend>
            <div className="row wrap">
              <label className="check">
                <input type="radio" name="sides" checked={draft.sides === 'all'} onChange={() => update({ sides: 'all', selectedSides: [] })} /> Все четыре
              </label>
              <label className="check">
                <input type="radio" name="sides" checked={draft.sides === 'selected'} onChange={() => update({ sides: 'selected' })} /> Выбранные:
              </label>
              {(['top', 'bottom', 'left', 'right'] as const).map(side => (
                <label key={side} className="check">
                  <input
                    type="checkbox"
                    disabled={draft.sides !== 'selected'}
                    checked={draft.selectedSides.includes(side)}
                    onChange={event =>
                      update({
                        selectedSides: event.target.checked ? [...draft.selectedSides, side] : draft.selectedSides.filter(item => item !== side),
                      })
                    }
                  />
                  {{ top: 'верх', bottom: 'низ', left: 'лево', right: 'право' }[side]}
                </label>
              ))}
            </div>
            {show('sides') && <small className="field-error">{show('sides')}</small>}
          </fieldset>
        )}
        <Field label="Заказчик текущего предложения, необязательно" hint="Это заказчик расчета. Адресат напоминания выбирается отдельно и его не меняет.">
          {props => <input {...props} value={draft.customerId} onChange={event => update({ customerId: event.target.value })} placeholder="например, новый клиент без ID" />}
        </Field>
        {form.notes.length > 0 && (
          <p className="small">
            Пересчет единиц: <b>{form.notes.join('; ')}</b>
          </p>
        )}
        <div className="row">
          <Button type="submit" variant="primary" icon={quote ? <RefreshCw size={14} aria-hidden="true" /> : <Calculator size={14} aria-hidden="true" />} busy={calculate.isPending} disabled={!kbVersion}>
            {quote && quote.status !== 'confirmed' ? 'Пересчитать (новая ревизия)' : 'Рассчитать'}
          </Button>
          {quote && (
            <Button
              variant="ghost"
              onClick={() => {
                onQuote(null);
                update({ quoteId: null });
              }}
            >
              Новый расчет
            </Button>
          )}
        </div>
      </form>
      {calculate.isPending && <LoadingState label={quote ? 'Пересчитываем: создается новая ревизия…' : 'Считаем по каталогу…'} />}
      {calculate.error && <ErrorState error={calculate.error} onRetry={() => form.request && calculate.mutate(form.request)} context="Расчет" />}
      {restored.isLoading && <LoadingState label="Восстанавливаем последний расчет…" />}
      {quote && <QuoteResult quote={quote} stale={stale || calculate.isPending} />}
    </Panel>
  );
}

function hintFor(value: string): string | undefined {
  if (!value.trim()) return 'мм, либо «45 см», «0,45 м»';
  const parsed = parseLength(value);
  if (!parsed.ok) return undefined;
  return parsed.converted ? `= ${parsed.mm} мм` : `${parsed.mm} мм`;
}

function ProductPrices({ product }: { product: CatalogProduct }) {
  return (
    <div className="product-prices small">
      <span className="muted">{product.category}</span>
      {product.prices.map((price, index) => (
        <span key={index} className="price-chip">
          {PRICE_TYPE[price.price_type] ?? price.price_type}: {price.amount_tg === null ? <em>цены нет в KB — ответ дает менеджер</em> : formatMoney(price.amount_tg)}
          {price.minimum_quantity ? ` (от ${price.minimum_quantity} шт)` : ''}
        </span>
      ))}
    </div>
  );
}

export function QuoteResult({ quote, stale }: { quote: Quote; stale: boolean }) {
  const tone = quote.status === 'needs_review' ? 'warn' : quote.status === 'confirmed' ? 'ok' : 'info';
  return (
    <div className={`quote-result${stale ? ' is-stale' : ''}`} aria-live="polite">
      {stale && <StaleNotice>Параметры изменены после расчета. Сумма ниже относится к ревизии {quote.revision} и не является новым итогом — пересчитайте.</StaleNotice>}
      <div className="quote-head">
        <div>
          <span className="small muted">
            Расчет <span className="mono">{quote.quote_id}</span> · ревизия {quote.revision}
          </span>
          <div className="row wrap">
            <StatusBadge tone={tone}>{STATUS_LABEL[quote.status]}</StatusBadge>
            {quote.preliminary && <StatusBadge tone="neutral">Предварительно, подтверждает менеджер</StatusBadge>}
          </div>
        </div>
        <div className="quote-total">
          <span className="small muted">Итого</span>
          <strong className={stale ? 'strike' : ''}>{quote.total_tg === null ? 'не определен' : formatMoney(quote.total_tg, { fixed2: true })}</strong>
        </div>
      </div>
      {(quote.product_name || quote.dimensions) && (
        <p className="small">
          {quote.product_name && <b>{quote.product_name}</b>}
          {quote.dimensions && <> · {formatDims(quote.dimensions)}</>} · количество: {quote.quantity ?? 'не указано'}
        </p>
      )}
      {quote.stale && <StaleNotice>Сервер пометил расчет устаревшим (изменилась версия прайса или склада). Создайте новую ревизию.</StaleNotice>}
      {quote.clarification && <p className="clarification">Нужно уточнение: {quote.clarification}</p>}
      {quote.components.length > 0 && (
        <TableWrap label="Позиции расчета">
          <table className="table compact">
            <thead>
              <tr>
                <th scope="col">Позиция</th>
                <th scope="col" className="num">
                  Сумма
                </th>
              </tr>
            </thead>
            <tbody>
              {quote.components.map((line, index) => (
                <tr key={index}>
                  <td>
                    {line.label}
                    {line.formula && <div className="small muted mono">{line.formula}</div>}
                  </td>
                  <td className="num">{formatMoney(line.amount_tg, { fixed2: true })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      <div className="small">
        <StatusBadge tone={quote.material_mapping_status === 'confirmed' ? 'ok' : 'warn'}>{MAPPING_LABEL[quote.material_mapping_status]}</StatusBadge>
        {quote.material_id && (
          <Details summary="Код материала для поддержки"><span className="mono">{quote.material_id}</span></Details>
        )}
      </div>
      {quote.unknown_components && quote.unknown_components.length > 0 && (
        <div className="state state-warn">
          <div>
            <strong>Неизвестные позиции — числа не выдумываются</strong>
            <ul className="plain small">
              {quote.unknown_components.map(item => (
                <li key={item.component}>{item.message_ru}</li>
              ))}
            </ul>
            {quote.known_subtotal_tg && <p className="small">Известная часть: {formatMoney(quote.known_subtotal_tg, { fixed2: true })} (не итог)</p>}
          </div>
        </div>
      )}
      {quote.diff && <QuoteDiffView diff={quote.diff} />}
      <Details summary="Источники расчета и политика округления">
        <EvidenceList evidence={[...(quote.evidence ?? []), ...quote.components.flatMap(line => line.evidence)]} />
        {quote.rounding_policy && <p className="small">Округление: {quote.rounding_policy}</p>}
      </Details>
    </div>
  );
}

function QuoteDiffView({ diff }: { diff: NonNullable<Quote['diff']> }) {
  return (
    <Details summary={`Изменения: ревизия ${diff.from_revision} → ${diff.to_revision}`} open>
      <p className="small">Изменено: {diff.changed_fields.join(', ') || '—'}</p>
      <TableWrap label="Разница ревизий">
        <table className="table compact">
          <thead>
            <tr>
              <th scope="col">Позиция</th>
              <th scope="col" className="num">
                Было
              </th>
              <th scope="col" className="num">
                Стало
              </th>
            </tr>
          </thead>
          <tbody>
            {diff.lines.map(line => (
              <tr key={line.component}>
                <td>{line.component}</td>
                <td className="num">{formatMoney(line.before_tg, { fixed2: true })}</td>
                <td className="num">{formatMoney(line.after_tg, { fixed2: true })}</td>
              </tr>
            ))}
            <tr>
              <th scope="row">Итого</th>
              <td className="num">{formatMoney(diff.total_before_tg, { fixed2: true })}</td>
              <td className="num">
                <b>{formatMoney(diff.total_after_tg, { fixed2: true })}</b>
              </td>
            </tr>
          </tbody>
        </table>
      </TableWrap>
    </Details>
  );
}

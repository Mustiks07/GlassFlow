import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Lock, MapPin } from 'lucide-react';
import { useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import { ApiError, asApiError } from '../../api/errors';
import type { Candidate, Dataset, Quote, Remnant } from '../../api/types';
import { formatDims, formatMoney } from '../../lib/format';
import { Button, ConfirmDialog, EmptyState, ErrorState, Field, LoadingState, Panel, StaleNotice, StatusBadge } from '../../ui/kit';
import { RemnantSvg, footprint } from '../cutting/RemnantSvg';
import { parseLocation, reasonLabel } from '../cutting/labels';
import { isMutable } from '../shell/dataset';

/**
 * Candidate remnant for the current quote + explicit confirmation.
 *
 * Contract facts (27.11.2026): Claude 3's POST /quotes returns candidate_refs/inventory_status
 * when inventory_mode is requested (it calls Claude 2's read-only find_candidates). Its
 * /quotes/{id}/confirm takes {expected_revision, confirmed_by} and does NOT reserve stock.
 * The reservation is therefore a separate explicit action on POST /remnants/{id}/reserve
 * (proposed to Claude 2) with expected_version + Idempotency-Key. A combined atomic
 * operation is recorded as a contract request in docs/status/CLAUDE_1_ILYAS.md.
 */
export function CandidatePanel({
  dataset,
  quote,
  quoteStale,
  onQuote,
}: {
  dataset: Dataset;
  quote: Quote | null;
  quoteStale: boolean;
  onQuote: (quote: Quote) => void;
}) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reserveOpen, setReserveOpen] = useState(false);
  const [confirmedBy, setConfirmedBy] = useState('');
  const [confirmKey, setConfirmKey] = useState(newIdempotencyKey);
  const [reserveKey, setReserveKey] = useState(newIdempotencyKey);
  const [reserved, setReserved] = useState<Remnant | null>(null);
  const dims = quote?.dimensions ?? null;
  const mapped = quote?.material_mapping_status === 'confirmed' && quote.material_id;
  const fromQuote = quote?.inventory_status && quote.inventory_status !== 'not_requested';

  // Older backends without inventory in the quote: ask Claude 2 directly (read-only).
  const direct = useQuery({
    queryKey: ['candidates', dataset.dataset_id, quote?.quote_id, quote?.revision, quote?.material_id, dims?.length_mm, dims?.width_mm],
    enabled: Boolean(mapped && dims && !quoteStale && !fromQuote),
    queryFn: ({ signal }) =>
      api.findCandidates(
        {
          dataset_id: dataset.dataset_id,
          material_id: quote!.material_id as string,
          dimensions: dims!,
          premium: false,
          inventory_mode: 'free_whole_remnants',
          base_plan_id: null,
        },
        signal,
      ),
  });
  const list: Candidate[] = fromQuote ? quote?.candidate_refs ?? [] : direct.data?.candidates ?? [];
  const reasonCodes = fromQuote ? quote?.inventory_reason_codes ?? [] : direct.data?.reason_codes ?? [];
  const remnants = useQuery({
    queryKey: ['remnants', dataset.dataset_id],
    enabled: list.length > 0,
    queryFn: ({ signal }) => api.listRemnants(dataset.dataset_id, signal),
  });

  const confirm = useMutation({
    mutationFn: () => api.confirmQuote(quote!.quote_id, { dataset_id: dataset.dataset_id, expected_revision: quote!.revision, confirmed_by: confirmedBy.trim() }, confirmKey),
    onSuccess: result => {
      onQuote(result);
      setConfirmOpen(false);
      setConfirmKey(newIdempotencyKey());
    },
    onError: error => {
      if (asApiError(error).kind === 'conflict') setConfirmKey(newIdempotencyKey());
    },
  });

  const reserve = useMutation({
    mutationFn: (candidate: Candidate) =>
      api.reserveRemnant(
        candidate.remnant_id,
        {
          dataset_id: dataset.dataset_id,
          expected_version: candidate.remnant_version,
          owner_context: { kind: 'quote', quote_id: quote!.quote_id, quote_revision: quote!.revision },
        },
        reserveKey,
      ),
    onSuccess: remnant => {
      setReserved(remnant);
      setReserveOpen(false);
      setReserveKey(newIdempotencyKey());
      queryClient.invalidateQueries({ queryKey: ['remnants', dataset.dataset_id] });
      queryClient.invalidateQueries({ queryKey: ['candidates', dataset.dataset_id] });
    },
    onError: error => {
      if (asApiError(error).kind === 'conflict') {
        // Show the actual state: refresh stock and candidates; a new key for the next deliberate attempt.
        queryClient.invalidateQueries({ queryKey: ['candidates', dataset.dataset_id] });
        queryClient.invalidateQueries({ queryKey: ['remnants', dataset.dataset_id] });
        setReserveKey(newIdempotencyKey());
      }
    },
  });

  const chosen = list.find(item => item.remnant_id === selectedId) ?? list[0] ?? null;
  const remnantOf = (candidate: Candidate): Remnant | undefined => remnants.data?.find(item => item.remnant_id === candidate.remnant_id);

  let body;
  if (!quote) body = <EmptyState title="Сначала рассчитайте предложение">Кандидаты склада ищутся для подтвержденного материала и размера.</EmptyState>;
  else if (quoteStale) body = <StaleNotice>Параметры расчета изменились. Кандидаты будут найдены заново после пересчета.</StaleNotice>;
  else if (quote.material_mapping_status !== 'confirmed' || quote.inventory_status === 'mapping_required')
    body = (
      <div className="state state-warn">
        <div>
          <strong>{quote.material_mapping_status === 'unmapped' ? 'Нет соответствия каталога складу' : 'Соответствие каталога складу не подтверждено'}</strong>
          <p>
            Подбор остатка невозможен без подтвержденного material_id. Это не означает физическое отсутствие стекла и не равно NEW: уточните
            у клиента материал или передайте менеджеру.
          </p>
        </div>
      </div>
    );
  else if (quote.inventory_status === 'service_unavailable')
    body = <ErrorState error={new ApiError('unavailable', 503, 'INVENTORY_SERVICE_UNAVAILABLE', 'Сервис склада не подключен к расчету.')} context="Подбор остатка" />;
  else if (!dims) body = <EmptyState title="Нет размеров детали">Укажите длину и ширину, чтобы подобрать кусок.</EmptyState>;
  else if (!fromQuote && direct.isLoading) body = <LoadingState label="Ищем свободные целые остатки…" />;
  else if (!fromQuote && direct.isError) body = <ErrorState error={direct.error} onRetry={() => direct.refetch()} context="Подбор остатка" />;
  else if (list.length === 0)
    body = (
      <div className="state state-info">
        <div>
          <strong>Свободного подходящего куска нет в режиме «без перестройки»</strong>
          <ul className="plain small">
            {(reasonCodes.length ? reasonCodes : ['unknown']).map(code => (
              <li key={code}>{reasonLabel(code)}</li>
            ))}
          </ul>
          <p className="small muted">
            Деталь не покрыта остатками (NEW для раскроя). Это не доказывает невозможность после общего перепланирования — сравнение доступно в
            разделе «Остатки и раскрой».
          </p>
        </div>
      </div>
    );
  else
    body = (
      <div className="stack">
        <ul className="candidate-list" aria-label="Подходящие остатки">
          {list.map(candidate => {
            const remnant = remnantOf(candidate);
            const location = parseLocation(candidate.location_raw);
            return (
              <li key={candidate.remnant_id}>
                <label className={`candidate${chosen?.remnant_id === candidate.remnant_id ? ' selected' : ''}`}>
                  <input type="radio" name="candidate" checked={chosen?.remnant_id === candidate.remnant_id} onChange={() => setSelectedId(candidate.remnant_id)} />
                  <span>
                    <strong className="mono">{candidate.remnant_id}</strong>
                    {remnant && (
                      <>
                        {' '}
                        · {formatDims(remnant.dimensions)} · {remnant.material_id}
                      </>
                    )}
                    <br />
                    <span className="small">
                      <MapPin size={12} aria-hidden="true" /> {candidate.location_raw}
                      {location.rack && ` (стеллаж ${location.rack}${location.cell ? `, ячейка ${location.cell}` : ''})`} · позиция ({candidate.x_mm}, {candidate.y_mm})
                      {candidate.rot ? ', поворот 90°' : ''}
                    </span>
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
        {chosen && dims && <CandidateScheme candidate={chosen} remnant={remnantOf(chosen)} dims={dims} />}
        <p className="small muted">Показ кандидата не резервирует кусок. Резерв — отдельное явное действие с проверкой версии.</p>
      </div>
    );

  const mutable = isMutable(dataset);
  const canConfirm = Boolean(quote && !quoteStale && !['confirmed', 'superseded', 'cancelled'].includes(quote.status) && quote.total_tg !== null && mutable);
  const canReserve = Boolean(quote && !quoteStale && chosen && mutable && !reserved);
  return (
    <Panel title="Подходящий остаток" subtitle="Свободные целые исходные куски; место хранения из поля «место».">
      {body}
      {quote && quote.status === 'confirmed' && (
        <StatusBadge tone="ok">
          Предложение подтверждено (ревизия {quote.revision}
          {quote.confirmed_by ? `, ${quote.confirmed_by}` : ''})
        </StatusBadge>
      )}
      {reserved && <StatusBadge tone="ok">Остаток {reserved.remnant_id} зарезервирован (версия {reserved.version})</StatusBadge>}
      {quote && !mutable && <p className="small muted">Подтверждение и резерв доступны только в рабочей копии. Исходный и конкурсный снимки не изменяются.</p>}
      {(canConfirm || canReserve) && (
        <div className="row">
          {canConfirm && (
            <Button variant="primary" icon={<CheckCircle2 size={14} aria-hidden="true" />} onClick={() => setConfirmOpen(true)}>
              Подтвердить предложение (рев. {quote!.revision})
            </Button>
          )}
          {canReserve && (
            <Button icon={<Lock size={14} aria-hidden="true" />} onClick={() => setReserveOpen(true)}>
              Зарезервировать {chosen!.remnant_id}
            </Button>
          )}
        </div>
      )}
      {quote && (
        <ConfirmDialog
          open={confirmOpen}
          onOpenChange={open => {
            setConfirmOpen(open);
            if (!open) confirm.reset();
          }}
          title="Подтвердить предложение"
          action={`Ревизия ${quote.revision} предложения ${quote.quote_id} станет подтвержденной. Цена остается предварительной до согласования условий менеджером; склад этим действием не резервируется.`}
          affected={[
            { label: 'Итог (предварительный)', value: formatMoney(quote.total_tg, { fixed2: true }) },
            { label: 'Ожидаемая ревизия', value: String(quote.revision) },
            { label: 'Заказчик', value: quote.customer_id ?? 'не указан' },
          ]}
          confirmLabel="Подтвердить предложение"
          onConfirm={() => confirmedBy.trim() && confirm.mutate()}
          busy={confirm.isPending}
          error={confirm.error}
        >
          <Field label="Кто подтверждает" required error={!confirmedBy.trim() ? 'Укажите менеджера' : undefined}>
            {props => <input {...props} value={confirmedBy} onChange={event => setConfirmedBy(event.target.value)} placeholder="например, M2" />}
          </Field>
        </ConfirmDialog>
      )}
      {quote && chosen && (
        <ConfirmDialog
          open={reserveOpen}
          onOpenChange={open => {
            setReserveOpen(open);
            if (!open) reserve.reset();
          }}
          title={`Зарезервировать ${chosen.remnant_id}`}
          action={`Целый кусок ${chosen.remnant_id} будет зарезервирован под предложение ${quote.quote_id} (ревизия ${quote.revision}). Сервер повторно проверит версию и свободный статус; при изменении вернется конфликт с актуальным состоянием.`}
          affected={[
            { label: 'Остаток', value: <span className="mono">{chosen.remnant_id}</span> },
            { label: 'Ожидаемая версия', value: String(chosen.remnant_version) },
            { label: 'Место', value: chosen.location_raw },
          ]}
          confirmLabel={`Зарезервировать ${chosen.remnant_id}`}
          onConfirm={() => reserve.mutate(chosen)}
          busy={reserve.isPending}
          error={reserve.error}
        >
          {reserve.error && asApiError(reserve.error).kind === 'conflict' && (
            <p className="small">Состояние склада обновлено. Выберите актуальный кусок из списка и подтвердите снова.</p>
          )}
        </ConfirmDialog>
      )}
    </Panel>
  );
}

function CandidateScheme({ candidate, remnant, dims }: { candidate: Candidate; remnant?: Remnant; dims: { length_mm: number; width_mm: number } }) {
  const length = candidate.length_mm ?? remnant?.dimensions.length_mm;
  const width = candidate.width_mm ?? remnant?.dimensions.width_mm;
  if (!length || !width) return <p className="small muted">Размер куска не получен — схема недоступна.</p>;
  const fp = footprint(dims.length_mm, dims.width_mm, candidate.rot);
  return (
    <figure className="scheme">
      <RemnantSvg
        remnant={{ remnant_id: candidate.remnant_id, length_mm: length, width_mm: width, tempered: candidate.tempered ?? remnant?.tempered }}
        parts={[{ part_id: 'Новая деталь', x_mm: candidate.x_mm, y_mm: candidate.y_mm, w_mm: fp.w, h_mm: fp.h, rot: candidate.rot, state: 'candidate', label: 'Деталь' }]}
        maxHeight={220}
      />
      <figcaption className="small">
        {candidate.remnant_id}: {length}×{width} мм, деталь {fp.w}×{fp.h} мм в ({candidate.x_mm}, {candidate.y_mm}). Пунктир — рабочий край 5 мм.
      </figcaption>
    </figure>
  );
}

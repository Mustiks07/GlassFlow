import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, MapPin } from 'lucide-react';
import { useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import { asApiError } from '../../api/errors';
import type { Candidate, Dataset, Quote, Remnant } from '../../api/types';
import { formatDims, formatMoney } from '../../lib/format';
import { Button, ConfirmDialog, EmptyState, ErrorState, LoadingState, Panel, StaleNotice, StatusBadge } from '../../ui/kit';
import { RemnantSvg, footprint } from '../cutting/RemnantSvg';
import { parseLocation, reasonLabel } from '../cutting/labels';
import { isMutable } from '../shell/dataset';

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
  const [confirmKey, setConfirmKey] = useState(newIdempotencyKey);
  const dims = quote?.dimensions ?? null;
  const mapped = quote?.material_mapping_status === 'confirmed' && quote.material_id;

  const candidates = useQuery({
    queryKey: ['candidates', dataset.dataset_id, quote?.quote_id, quote?.revision, quote?.material_id, dims?.length_mm, dims?.width_mm],
    enabled: Boolean(mapped && dims && !quoteStale),
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
  const remnants = useQuery({
    queryKey: ['remnants', dataset.dataset_id],
    enabled: Boolean(candidates.data?.candidates.length),
    queryFn: ({ signal }) => api.listRemnants(dataset.dataset_id, signal),
  });

  const confirm = useMutation({
    mutationFn: (candidate: Candidate | null) =>
      api.confirmQuote(
        quote!.quote_id,
        {
          dataset_id: dataset.dataset_id,
          expected_revision: quote!.revision,
          remnant_id: candidate?.remnant_id ?? null,
          expected_remnant_version: candidate?.remnant_version ?? null,
        },
        confirmKey,
      ),
    onSuccess: result => {
      onQuote(result);
      setConfirmOpen(false);
      setConfirmKey(newIdempotencyKey());
      queryClient.invalidateQueries({ queryKey: ['remnants', dataset.dataset_id] });
      queryClient.invalidateQueries({ queryKey: ['candidates', dataset.dataset_id] });
    },
    onError: error => {
      if (asApiError(error).kind === 'conflict') {
        // Show the actual current state: refetch candidates and remnants; keep the dialog open with the conflict.
        queryClient.invalidateQueries({ queryKey: ['candidates', dataset.dataset_id] });
        queryClient.invalidateQueries({ queryKey: ['remnants', dataset.dataset_id] });
        setConfirmKey(newIdempotencyKey());
      }
    },
  });

  const list = candidates.data?.candidates ?? [];
  const chosen = list.find(item => item.remnant_id === selectedId) ?? list[0] ?? null;
  const remnantOf = (candidate: Candidate): Remnant | undefined => remnants.data?.find(item => item.remnant_id === candidate.remnant_id);

  let body;
  if (!quote) body = <EmptyState title="Сначала рассчитайте предложение">Кандидаты склада ищутся для подтвержденного материала и размера.</EmptyState>;
  else if (quoteStale) body = <StaleNotice>Параметры расчета изменились. Кандидаты будут найдены заново после пересчета.</StaleNotice>;
  else if (quote.material_mapping_status !== 'confirmed')
    body = (
      <div className="state state-warn">
        <div>
          <strong>{quote.material_mapping_status === 'unmapped' ? 'Нет соответствия каталога складу' : 'Соответствие неоднозначно'}</strong>
          <p>
            Подбор остатка невозможен без подтвержденного material_id. Это не означает физическое отсутствие стекла и не равно NEW: уточните
            у клиента материал или передайте менеджеру.
          </p>
        </div>
      </div>
    );
  else if (!dims) body = <EmptyState title="Нет размеров детали">Укажите длину и ширину, чтобы подобрать кусок.</EmptyState>;
  else if (candidates.isLoading) body = <LoadingState label="Ищем свободные целые остатки…" />;
  else if (candidates.isError) body = <ErrorState error={candidates.error} onRetry={() => candidates.refetch()} context="Подбор остатка" />;
  else if (list.length === 0)
    body = (
      <div className="state state-info">
        <div>
          <strong>Свободного подходящего куска нет в режиме «без перестройки»</strong>
          <ul className="plain small">
            {(candidates.data?.reason_codes.length ? candidates.data.reason_codes : ['unknown']).map(code => (
              <li key={code}>{reasonLabel(code)}</li>
            ))}
          </ul>
          <p className="small muted">
            Деталь не покрыта остатками (NEW для раскроя). Это не доказывает невозможность после общего перепланирования — сравнение доступно
            в разделе «Остатки и раскрой». Область поиска: {candidates.data?.scope ?? 'не сообщена'}.
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
                    {remnant && <> · {formatDims(remnant.dimensions)} · {remnant.material_id}</>}
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
        {chosen && dims && (
          <CandidateScheme candidate={chosen} remnant={remnantOf(chosen)} dims={dims} />
        )}
        <p className="small muted">Показ кандидата не резервирует кусок. Резерв создается только после подтверждения ниже.</p>
      </div>
    );

  const canConfirm = Boolean(quote && !quoteStale && quote.status !== 'confirmed' && quote.total_tg !== null && isMutable(dataset));
  return (
    <Panel title="Подходящий остаток" subtitle="Свободные целые исходные куски; место хранения из поля «место».">
      {body}
      {quote && quote.status === 'confirmed' && <StatusBadge tone="ok">Предложение подтверждено (ревизия {quote.revision})</StatusBadge>}
      {quote && !isMutable(dataset) && (
        <p className="small muted">Подтверждение и резерв доступны только в рабочей копии. Исходный и конкурсный снимки не изменяются.</p>
      )}
      {canConfirm && (
        <div className="row">
          <Button variant="primary" icon={<CheckCircle2 size={14} aria-hidden="true" />} onClick={() => setConfirmOpen(true)}>
            {chosen ? `Подтвердить и зарезервировать ${chosen.remnant_id}` : 'Подтвердить предложение без остатка'}
          </Button>
        </div>
      )}
      {quote && (
        <ConfirmDialog
          open={confirmOpen}
          onOpenChange={open => {
            setConfirmOpen(open);
            if (!open) confirm.reset();
          }}
          title={chosen ? 'Подтвердить предложение и резерв' : 'Подтвердить предложение'}
          action={
            chosen
              ? `Предложение ${quote.quote_id} (ревизия ${quote.revision}) будет подтверждено, а остаток ${chosen.remnant_id} — зарезервирован целиком одной транзакцией. Сервер повторно проверит версии.`
              : `Предложение ${quote.quote_id} (ревизия ${quote.revision}) будет подтверждено без резерва остатка.`
          }
          affected={[
            { label: 'Итог (предварительный)', value: formatMoney(quote.total_tg, { fixed2: true }) },
            ...(chosen
              ? [
                  { label: 'Остаток', value: <span className="mono">{chosen.remnant_id}</span> },
                  { label: 'Ожидаемая версия остатка', value: String(chosen.remnant_version) },
                  { label: 'Место', value: chosen.location_raw },
                ]
              : []),
            { label: 'Заказчик', value: quote.customer_id ?? 'не указан' },
          ]}
          confirmLabel={chosen ? `Подтвердить и зарезервировать ${chosen.remnant_id}` : 'Подтвердить'}
          onConfirm={() => confirm.mutate(chosen)}
          busy={confirm.isPending}
          error={confirm.error}
        >
          {confirm.error && asApiError(confirm.error).kind === 'conflict' && (
            <p className="small">Состояние склада обновлено. Выберите актуальный кусок из списка и подтвердите снова.</p>
          )}
        </ConfirmDialog>
      )}
      {confirm.isSuccess && <StatusBadge tone="ok">Подтверждено: {confirm.data.quote_id}, ревизия {confirm.data.revision}</StatusBadge>}
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

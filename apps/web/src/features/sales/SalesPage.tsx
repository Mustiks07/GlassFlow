import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, RefreshCw, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import type { Buyer, CutPlan, Dataset, SaleCard } from '../../api/types';
import { formatDims, formatInt, formatMoney } from '../../lib/format';
import { href } from '../../state/router';
import { useAppStore } from '../../state/store';
import { Button, ConfirmDialog, Details, EmptyState, ErrorState, LoadingState, Metric, Panel, StatusBadge, TableWrap, type Tone } from '../../ui/kit';
import { RequireDataset } from '../shell/RequireDataset';

export function SalesPage() {
  return <RequireDataset>{dataset => <Sales dataset={dataset} key={dataset.dataset_id} />}</RequireDataset>;
}

const CARD_STATUS: Record<NonNullable<SaleCard['status']>, { label: string; tone: Tone }> = {
  draft: { label: 'Черновик', tone: 'neutral' },
  checked: { label: 'Проверена', tone: 'info' },
  ready: { label: 'Готова к экспорту', tone: 'ok' },
  stale: { label: 'Устарела — экспорт заблокирован', tone: 'stale' },
};

function Sales({ dataset }: { dataset: Dataset }) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const activePlanId = useAppStore(state => state.activePlanIds[dataset.dataset_id]);
  const plans = useQuery({ queryKey: ['plans', dataset.dataset_id], queryFn: ({ signal }) => api.listPlans(dataset.dataset_id, signal) });
  const buyers = useQuery({ queryKey: ['buyers'], queryFn: ({ signal }) => api.listBuyers(signal) });
  const cards = useQuery({ queryKey: ['sale-cards', dataset.dataset_id], queryFn: ({ signal }) => api.listSaleCards(dataset.dataset_id, signal) });
  const [planId, setPlanId] = useState<string>('');
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const chosenPlan: CutPlan | undefined =
    plans.data?.find(plan => plan.plan_id === (planId || activePlanId)) ?? plans.data?.find(plan => plan.status === 'committed') ?? plans.data?.[0];
  const registryVersion = buyers.data?.[0]?.registry_version ?? 'current';

  const generate = useMutation({
    mutationFn: (plan: CutPlan) =>
      api.createSaleCards({ dataset_id: dataset.dataset_id, plan_id: plan.plan_id, plan_revision: plan.revision, buyer_registry_version: registryVersion }, key),
    onSuccess: () => {
      setOpen(false);
      setKey(newIdempotencyKey());
      queryClient.invalidateQueries({ queryKey: ['sale-cards', dataset.dataset_id] });
    },
  });

  const list = cards.data ?? [];
  const staleCount = list.filter(card => card.status === 'stale').length;
  const exportReady = list.length >= 5 && staleCount === 0 && list.every(card => card.status === undefined || card.status === 'ready');
  const buyerByName = useMemo(() => new Map((buyers.data ?? []).map(buyer => [buyer.name, buyer])), [buyers.data]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Продажа остатков</p>
          <h1>Пять карточек свободных исходных кусков</h1>
          <p className="lead">Карточки связаны с выбранной ревизией плана. Цена = полная площадь × ставка materials × коэффициент 0,30–0,70 (только для карточки, не скидка каталога).</p>
        </div>
      </header>
      <Panel
        title="План-основание"
        actions={
          <a className="link-btn" href={href('cutting')}>
            Открыть раскрой
          </a>
        }
      >
        {plans.isLoading && <LoadingState />}
        {plans.isError && <ErrorState error={plans.error} onRetry={() => plans.refetch()} context="Планы раскроя" />}
        {plans.data && plans.data.length === 0 && <EmptyState title="Планов раскроя нет">Сначала постройте и подтвердите план в разделе «Остатки и раскрой».</EmptyState>}
        {plans.data && plans.data.length > 0 && chosenPlan && (
          <div className="row wrap align-end">
            <label className="inline-field">
              План
              <select value={chosenPlan.plan_id} onChange={event => setPlanId(event.target.value)}>
                {plans.data.map(plan => (
                  <option key={plan.plan_id} value={plan.plan_id}>
                    {plan.plan_id} · ревизия {plan.revision} · {plan.status}
                  </option>
                ))}
              </select>
            </label>
            <Metric label="Свободных исходных кусков" value={chosenPlan.free_original_remnant_ids.length} tone={chosenPlan.free_original_remnant_ids.length >= 5 ? 'ok' : 'warn'} />
            <Button variant="primary" icon={<Sparkles size={14} aria-hidden="true" />} onClick={() => setOpen(true)} disabled={chosenPlan.free_original_remnant_ids.length < 5}>
              Сгенерировать 5 карточек
            </Button>
            {chosenPlan.free_original_remnant_ids.length < 5 && (
              <p className="small text-warn">
                Меньше пяти свободных кусков. Пересчитайте раскрой с условием пяти свободных; фиктивные куски не создаются.
              </p>
            )}
          </div>
        )}
      </Panel>

      <Panel
        title="Карточки"
        subtitle={staleCount ? `${staleCount} карточек устарели после изменения плана или резерва — перепроверьте` : undefined}
        actions={<StatusBadge tone={exportReady ? 'ok' : list.length ? 'warn' : 'neutral'}>{exportReady ? 'Экспорт разрешен' : list.length ? 'Экспорт заблокирован' : 'Нет карточек'}</StatusBadge>}
      >
        {cards.isLoading && <LoadingState />}
        {cards.isError && <ErrorState error={cards.error} onRetry={() => cards.refetch()} context="Карточки" />}
        {cards.data && list.length === 0 && <EmptyState title="Карточек пока нет">Сгенерируйте их для выбранного плана.</EmptyState>}
        <div className="cards-grid">
          {list.map(card => (
            <SaleCardView key={card.card_id ?? card.remnant_id} dataset={dataset} card={card} buyerByName={buyerByName} />
          ))}
        </div>
      </Panel>

      <BuyersRegistry buyers={buyers.data} state={buyers} />

      {chosenPlan && (
        <ConfirmDialog
          open={open}
          onOpenChange={value => {
            setOpen(value);
            if (!value) generate.reset();
          }}
          title="Сгенерировать карточки"
          action="Сервер выберет пять разных полностью неиспользованных исходных кусков выбранной ревизии плана и подберет по три покупателя из реестра по профилю применения."
          affected={[
            { label: 'План', value: `${chosenPlan.plan_id} · ревизия ${chosenPlan.revision}` },
            { label: 'Свободных кусков', value: String(chosenPlan.free_original_remnant_ids.length) },
            { label: 'Версия реестра покупателей', value: registryVersion },
          ]}
          confirmLabel="Сгенерировать"
          onConfirm={() => generate.mutate(chosenPlan)}
          busy={generate.isPending}
          error={generate.error}
        />
      )}
    </div>
  );
}

function SaleCardView({ dataset, card, buyerByName }: { dataset: Dataset; card: SaleCard; buyerByName: Map<string, Buyer> }) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const recheck = useMutation({
    mutationFn: () => api.recheckSaleCard(card.card_id as string, dataset.dataset_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sale-cards', dataset.dataset_id] }),
  });
  const status = card.status ? CARD_STATUS[card.status] : null;
  return (
    <article className={`sale-card${card.status === 'stale' ? ' is-stale' : ''}`} aria-label={`Карточка ${card.remnant_id}`}>
      <header>
        <span className="mono">{card.remnant_id}</span>
        {status && <StatusBadge tone={status.tone}>{status.label}</StatusBadge>}
      </header>
      <h3>{card.title}</h3>
      <p className="small">{card.description}</p>
      <dl className="kv compact">
        {card.dimensions && (
          <div className="kv-row">
            <dt>Размер</dt>
            <dd>{formatDims(card.dimensions)}</dd>
          </div>
        )}
        {card.material_id && (
          <div className="kv-row">
            <dt>Материал</dt>
            <dd className="mono">{card.material_id}</dd>
          </div>
        )}
        {card.location_raw && (
          <div className="kv-row">
            <dt>Место</dt>
            <dd>{card.location_raw}</dd>
          </div>
        )}
        <div className="kv-row">
          <dt>Цена карточки</dt>
          <dd>
            <strong>{formatMoney(card.price_tg, { fixed2: true })}</strong>
          </dd>
        </div>
        {card.material_valuation_tg && (
          <div className="kv-row">
            <dt>Оценка материала (100%)</dt>
            <dd>
              {formatMoney(card.material_valuation_tg, { fixed2: true })} × коэффициент {card.discount_factor ?? '—'}
            </dd>
          </div>
        )}
        {card.plan_revision !== undefined && (
          <div className="kv-row">
            <dt>План</dt>
            <dd className="mono">
              {card.plan_id} · ревизия {card.plan_revision}
            </dd>
          </div>
        )}
      </dl>
      <div>
        <strong className="small">Целевой покупатель: {card.target_buyer}</strong>
        <ol className="buyers small">
          {card.top3_buyers.map(name => {
            const buyer = buyerByName.get(name);
            return (
              <li key={name}>
                {name}
                {buyer && (
                  <>
                    {' '}
                    · {buyer.category}, {buyer.city}
                    <Details summary="Основание">
                      <p>{card.buyer_evidence?.[name] ?? buyer.why}</p>
                      <a href={buyer.source_url} target="_blank" rel="noreferrer noopener">
                        Источник <ExternalLink size={11} aria-hidden="true" />
                      </a>
                    </Details>
                  </>
                )}
                {!buyer && <span className="text-warn"> · нет в текущем реестре</span>}
              </li>
            );
          })}
        </ol>
      </div>
      {card.stale_reason && <p className="small text-warn">{card.stale_reason}</p>}
      {card.card_id && (
        <Button variant="ghost" icon={<RefreshCw size={14} aria-hidden="true" />} onClick={() => recheck.mutate()} busy={recheck.isPending}>
          Перепроверить
        </Button>
      )}
      {recheck.error && <ErrorState error={recheck.error} />}
    </article>
  );
}

function BuyersRegistry({ buyers, state }: { buyers: Buyer[] | undefined; state: { isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown } }) {
  const [filter, setFilter] = useState('');
  const stats = useMemo(() => {
    const list = buyers ?? [];
    return {
      total: list.length,
      unique: new Set(list.map(buyer => buyer.name.trim().toLowerCase())).size,
      astana: list.filter(buyer => /астана/i.test(buyer.city)).length,
      categories: new Set(list.map(buyer => buyer.category)).size,
    };
  }, [buyers]);
  const shown = (buyers ?? []).filter(buyer => !filter || `${buyer.name} ${buyer.category} ${buyer.city}`.toLowerCase().includes(filter.toLowerCase()));
  return (
    <Panel title="Реестр покупателей" subtitle="Публичные организации. Score — экспертная релевантность профиля, не вероятность покупки. Сообщения не отправляются.">
      {state.isLoading && <LoadingState />}
      {state.isError && <ErrorState error={state.error} onRetry={() => state.refetch()} context="Реестр" />}
      {buyers && (
        <>
          <div className="metrics-row">
            <Metric label="Организаций" value={stats.total} tone={stats.total === 50 && stats.unique === 50 ? 'ok' : 'warn'} detail={`уникальных: ${stats.unique}`} />
            <Metric label="В Астане" value={stats.astana} tone={stats.astana >= 30 ? 'ok' : 'warn'} detail="требуется ≥ 30" />
            <Metric label="Категорий" value={stats.categories} tone={stats.categories >= 5 ? 'ok' : 'warn'} detail="требуется ≥ 5" />
          </div>
          <label className="inline-field">
            Поиск
            <input type="search" value={filter} onChange={event => setFilter(event.target.value)} />
          </label>
          <TableWrap label="Покупатели" maxHeight={420}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Организация</th>
                  <th scope="col">Город</th>
                  <th scope="col">Категория</th>
                  <th scope="col">Возможное применение</th>
                  <th scope="col" className="num">
                    Score
                  </th>
                  <th scope="col">Источник</th>
                </tr>
              </thead>
              <tbody>
                {shown.map(buyer => (
                  <tr key={buyer.name}>
                    <td>
                      <a href={buyer.url} target="_blank" rel="noreferrer noopener">
                        {buyer.name}
                      </a>
                    </td>
                    <td>{buyer.city}</td>
                    <td>{buyer.category}</td>
                    <td className="small">{buyer.why}</td>
                    <td className="num">{formatInt(buyer.score)}</td>
                    <td>
                      <a href={buyer.source_url} target="_blank" rel="noreferrer noopener" aria-label={`Источник: ${buyer.name}`}>
                        <ExternalLink size={13} aria-hidden="true" />
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </>
      )}
    </Panel>
  );
}

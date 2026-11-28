import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, RefreshCw, Sparkles, Upload } from 'lucide-react';
import { useMemo, useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import { asApiError } from '../../api/errors';
import type { Buyer, Dataset, PlanSummary, SaleCard } from '../../api/types';
import { formatInt, formatMoney } from '../../lib/format';
import { href } from '../../state/router';
import { useAppStore } from '../../state/store';
import { Button, ConfirmDialog, Details, EmptyState, ErrorState, Field, LoadingState, Metric, Panel, StatusBadge, TableWrap, type Tone } from '../../ui/kit';
import { isMutable } from '../shell/dataset';
import { RequireDataset } from '../shell/RequireDataset';
import { PLAN_STATUS_LABEL } from '../cutting/labels';
import { humanText } from '../../ui/human';

export function SalesPage() {
  return <RequireDataset>{dataset => <Sales dataset={dataset} key={dataset.dataset_id} />}</RequireDataset>;
}

const CARD_STATUS: Record<NonNullable<SaleCard['status']>, { label: string; tone: Tone }> = {
  draft: { label: 'Черновик — требует проверки', tone: 'neutral' },
  ready: { label: 'Проверена, готова к экспорту', tone: 'ok' },
  stale: { label: 'Устарела — экспорт заблокирован', tone: 'stale' },
};

const FACTOR_RE = /^0\.(?:[3-6]\d?|70?)$/;

/** Allowed card coefficient: 0.30–0.70 inclusive, decimal string (validated again by the server). */
export function factorError(value: string): string | null {
  const text = value.replace(',', '.').trim();
  if (!FACTOR_RE.test(text)) return 'Коэффициент от 0,30 до 0,70 (например 0,50)';
  return null;
}

function useRegistry(datasetId: string) {
  const { api } = useApi();
  const registries = useQuery({ queryKey: ['buyer-registries', datasetId], queryFn: ({ signal }) => api.listBuyerRegistries(datasetId, signal) });
  const version = registries.data?.at(-1)?.version ?? null;
  const buyers = useQuery({
    queryKey: ['buyers', datasetId, version],
    enabled: Boolean(version),
    queryFn: ({ signal }) => api.listBuyers(datasetId, version as string, signal),
  });
  return { registries, version, buyers };
}

function Sales({ dataset }: { dataset: Dataset }) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const activePlanId = useAppStore(state => state.activePlanIds[dataset.dataset_id]);
  const plans = useQuery({ queryKey: ['plans', dataset.dataset_id], queryFn: ({ signal }) => api.listPlans(dataset.dataset_id, signal) });
  const { registries, version, buyers } = useRegistry(dataset.dataset_id);
  const cards = useQuery({ queryKey: ['sale-cards', dataset.dataset_id], queryFn: ({ signal }) => api.listSaleCards(dataset.dataset_id, signal) });
  const [planId, setPlanId] = useState<string>('');
  const [factor, setFactor] = useState('0.50');
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const chosenPlan: PlanSummary | undefined =
    plans.data?.find(plan => plan.plan_id === (planId || activePlanId)) ?? plans.data?.find(plan => plan.status === 'committed') ?? plans.data?.[0];
  // Live re-check of fully free ORIGINAL pieces right now (C2 /plans/{id}/free-remnants), not the stored list.
  const free = useQuery({
    queryKey: ['free-remnants', dataset.dataset_id, chosenPlan?.plan_id, chosenPlan?.revision],
    enabled: Boolean(chosenPlan),
    queryFn: ({ signal }) => api.freeRemnants(chosenPlan!.plan_id, dataset.dataset_id, signal),
  });
  const freeCount = free.data?.count ?? 0;

  const generate = useMutation({
    mutationFn: (plan: PlanSummary) =>
      api.createSaleCards(
        { dataset_id: dataset.dataset_id, plan_id: plan.plan_id, plan_revision: plan.revision, buyer_registry_version: version as string, factor: factor.replace(',', '.') },
        key,
      ),
    onSuccess: () => {
      setOpen(false);
      setKey(newIdempotencyKey());
      queryClient.invalidateQueries({ queryKey: ['sale-cards', dataset.dataset_id] });
    },
  });

  const list = cards.data ?? [];
  const staleCount = list.filter(card => card.status === 'stale').length;
  const readyCount = list.filter(card => card.status === 'ready').length;
  const exportReady = readyCount >= 5 && staleCount === 0;
  const buyerByName = useMemo(() => new Map((buyers.data ?? []).map(buyer => [buyer.name, buyer])), [buyers.data]);
  const factorProblem = factorError(factor);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Продажа остатков</p>
          <h1>Пять карточек свободных исходных кусков</h1>
          <p className="lead">
            Карточки связаны с выбранной ревизией плана. Цена = полная площадь × ставка справочника материалов × коэффициент 0,30–0,70 — только для карточки,
            не скидка каталога. Публикация вовне не выполняется.
          </p>
        </div>
      </header>
      <Panel
        title="План-основание и реестр"
        actions={
          <a className="link-btn" href={href('cutting')}>
            Открыть раскрой
          </a>
        }
      >
        {plans.isLoading && <LoadingState />}
        {plans.isError && <ErrorState error={plans.error} onRetry={() => plans.refetch()} context="Планы раскроя" />}
        {plans.data && plans.data.length === 0 && <EmptyState title="Планов раскроя нет">Сначала постройте и подтвердите план в разделе «Остатки и раскрой».</EmptyState>}
        {registries.isError && <ErrorState error={registries.error} onRetry={() => registries.refetch()} context="Реестры покупателей" />}
        {registries.data && registries.data.length === 0 && (
          <EmptyState title="Реестр покупателей не импортирован">Загрузите buyers_candidate.csv и evidence.json ниже — без реестра карточки не создаются.</EmptyState>
        )}
        {plans.data && plans.data.length > 0 && chosenPlan && (
          <div className="row wrap align-end">
            <label className="inline-field">
              План
              <select value={chosenPlan.plan_id} onChange={event => setPlanId(event.target.value)}>
                {plans.data.map(plan => (
                  <option key={plan.plan_id} value={plan.plan_id}>
                    План · ревизия {plan.revision} · {PLAN_STATUS_LABEL[plan.status] ?? 'Требует проверки'} · {Math.round((plan.coverage ?? 0) * 100)}%
                  </option>
                ))}
              </select>
            </label>
            <Metric
              label="Свободных исходных кусков (сейчас)"
              value={free.isLoading ? '…' : free.isError ? 'ошибка' : freeCount}
              tone={free.data?.minimum_free_remnants_met ? 'ok' : 'warn'}
              detail={free.data?.no_longer_free_remnant_ids.length ? `заняты после плана: ${free.data.no_longer_free_remnant_ids.join(', ')}` : 'живая перепроверка склада'}
            />
            <Metric label="Реестр покупателей" value={version ? 'Подключён' : 'Не выбран'} />
            <Field label="Коэффициент" error={factorProblem ?? undefined} hint="0,50 — проектное значение, не оценка рынка">
              {props => <input {...props} value={factor} onChange={event => setFactor(event.target.value)} style={{ width: 110 }} />}
            </Field>
            <Button
              variant="primary"
              icon={<Sparkles size={14} aria-hidden="true" />}
              onClick={() => setOpen(true)}
              disabled={freeCount < 5 || !version || Boolean(factorProblem)}
            >
              Сгенерировать 5 карточек
            </Button>
            {free.isError && <ErrorState error={free.error} onRetry={() => free.refetch()} context="Перепроверка свободных кусков" />}
            {free.data && freeCount < 5 && (
              <p className="small text-warn">Меньше пяти свободных кусков. Пересчитайте раскрой с условием пяти свободных; фиктивные куски не создаются.</p>
            )}
          </div>
        )}
      </Panel>

      <Panel
        title="Карточки"
        subtitle={staleCount ? `${staleCount} карточек устарели после изменения плана или резерва — перепроверьте или создайте заново` : undefined}
        actions={
          <StatusBadge tone={exportReady ? 'ok' : list.length ? 'warn' : 'neutral'}>
            {exportReady ? 'Экспорт разрешен' : list.length ? `Экспорт заблокирован: готовы ${readyCount} из 5` : 'Нет карточек'}
          </StatusBadge>
        }
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

      <BuyersRegistry dataset={dataset} buyers={buyers.data} state={buyers} version={version} />

      {chosenPlan && version && (
        <ConfirmDialog
          open={open}
          onOpenChange={value => {
            setOpen(value);
            if (!value) generate.reset();
          }}
          title="Сгенерировать карточки"
          action="Сервер выберет пять разных полностью неиспользованных исходных кусков выбранной ревизии плана и подберет по три покупателя из реестра по профилю применения."
          affected={[
            { label: 'План', value: <span>Ревизия {chosenPlan.revision}<Details summary="Номер плана для поддержки">{chosenPlan.plan_id}</Details></span> },
            { label: 'Свободных кусков сейчас', value: String(freeCount) },
            { label: 'Коэффициент', value: factor.replace('.', ',') },
            { label: 'Реестр покупателей', value: <span>Выбранный реестр<Details summary="Версия для поддержки">{version}</Details></span> },
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
  const [factor, setFactor] = useState(card.factor ?? '0.50');
  const [key, setKey] = useState(newIdempotencyKey);
  const recheck = useMutation({
    mutationFn: () => api.recheckSaleCard(card.card_id as string, dataset.dataset_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sale-cards', dataset.dataset_id] }),
  });
  const update = useMutation({
    mutationFn: () => api.updateSaleCard(card.card_id as string, { dataset_id: dataset.dataset_id, expected_version: card.version ?? 0, factor: factor.replace(',', '.') }, key),
    onSuccess: () => {
      setKey(newIdempotencyKey());
      queryClient.invalidateQueries({ queryKey: ['sale-cards', dataset.dataset_id] });
    },
    onError: error => {
      if (asApiError(error).kind === 'conflict') {
        setKey(newIdempotencyKey());
        queryClient.invalidateQueries({ queryKey: ['sale-cards', dataset.dataset_id] });
      }
    },
  });
  const status = card.status ? CARD_STATUS[card.status] : null;
  const problem = factorError(factor);
  return (
    <article className={`sale-card${card.status === 'stale' ? ' is-stale' : ''}`} aria-label={`Карточка ${card.remnant_id}`}>
      <header>
        <span className="mono">{card.remnant_id}</span>
        {status && <StatusBadge tone={status.tone}>{status.label}</StatusBadge>}
      </header>
      <h3>{card.title}</h3>
      <p className="small">{card.description}</p>
      <dl className="kv compact">
        <div className="kv-row">
          <dt>Цена карточки</dt>
          <dd>
            <strong>{formatMoney(card.price_tg, { fixed2: true })}</strong>
          </dd>
        </div>
        <div className="kv-row">
          <dt>Коэффициент</dt>
          <dd>{(card.factor ?? '—').replace('.', ',')} от оценки материала</dd>
        </div>
        {card.plan_id && (
          <div className="kv-row">
            <dt>План</dt>
            <dd className="mono">
              Ревизия {card.plan_revision}<Details summary="Номер плана для поддержки">{card.plan_id}</Details>
            </dd>
          </div>
        )}
        {card.remnant_version !== undefined && card.remnant_version !== null && (
          <div className="kv-row">
            <dt>Версия куска</dt>
            <dd>{card.remnant_version}</dd>
          </div>
        )}
      </dl>
      {card.assumptions && <p className="small muted">{card.assumptions}</p>}
      <div>
        <strong className="small">Целевой покупатель: {card.target_buyer}</strong>
        <ol className="buyers small">
          {card.top3_buyers.map(name => {
            const buyer = buyerByName.get(name);
            return (
              <li key={name}>
                {name}
                {buyer ? (
                  <>
                    {' '}
                    · {buyer.category}, {buyer.city}
                    <Details summary="Почему этот покупатель">
                      <p>{buyer.why}</p>
                      {card.buyer_matches?.filter(match => match.name === name).map(match => <div key={match.buyer_id}>
                        <p>{match.explanation}</p><p>{match.activity}</p>
                        <p>{match.dimensions_basis}</p>
                        <p>Материал {match.material_id} · {match.dimensions.length_mm}×{match.dimensions.width_mm} мм · версия куска {match.remnant_version} · проверено {match.checked_at}</p>
                        <p>Интерес покупателя не подтвержден. {match.constraints?.join('; ')}</p>
                      </div>)}
                      <a href={buyer.source_url} target="_blank" rel="noreferrer noopener">
                        Источник <ExternalLink size={11} aria-hidden="true" />
                      </a>
                    </Details>
                  </>
                ) : (
                  <span className="text-warn"> · нет в загруженном реестре</span>
                )}
              </li>
            );
          })}
        </ol>
      </div>
      {card.stale_reason && <><p className="small text-warn">{humanText(card.stale_reason, 'Данные карточки изменились. Проверьте свободный кусок и создайте актуальную карточку.')}</p><Details summary="Причина изменения для поддержки">{card.stale_reason}</Details></>}
      {card.card_id && card.status !== 'stale' && isMutable(dataset) && (
        <form
          className="row align-end"
          onSubmit={event => {
            event.preventDefault();
            if (!problem) update.mutate();
          }}
        >
          <Field label="Новый коэффициент" error={problem ?? undefined}>
            {props => <input {...props} value={factor} onChange={event => setFactor(event.target.value)} style={{ width: 100 }} />}
          </Field>
          <Button type="submit" busy={update.isPending} disabled={Boolean(problem) || factor.replace(',', '.') === card.factor}>
            Пересчитать цену
          </Button>
        </form>
      )}
      {update.error && <ErrorState error={update.error} />}
      {card.card_id && (
        <Button variant="ghost" icon={<RefreshCw size={14} aria-hidden="true" />} onClick={() => recheck.mutate()} busy={recheck.isPending}>
          Перепроверить по текущему плану и складу
        </Button>
      )}
      {recheck.error && <ErrorState error={recheck.error} />}
    </article>
  );
}

function BuyersRegistry({
  dataset,
  buyers,
  state,
  version,
}: {
  dataset: Dataset;
  buyers: Buyer[] | undefined;
  state: { isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown };
  version: string | null;
}) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState('');
  const [csv, setCsv] = useState<File | null>(null);
  const [evidence, setEvidence] = useState<File | null>(null);
  const [key, setKey] = useState(newIdempotencyKey);
  const importMutation = useMutation({
    mutationFn: () => api.importBuyers(dataset.dataset_id, csv!, evidence!, key),
    onSuccess: () => {
      setKey(newIdempotencyKey());
      queryClient.invalidateQueries({ queryKey: ['buyer-registries', dataset.dataset_id] });
    },
  });
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
    <Panel title="Реестр покупателей" subtitle="Публичные организации. Оценка соответствия профиля — экспертный ориентир, не вероятность покупки. Сообщения не отправляются.">
      <Details summary="Импорт реестра (buyers_candidate.csv + evidence.json)">
        <form
          className="row wrap align-end"
          onSubmit={event => {
            event.preventDefault();
            if (csv && evidence) importMutation.mutate();
          }}
        >
          <Field label="CSV реестра">{props => <input {...props} type="file" accept=".csv" onChange={event => setCsv(event.target.files?.[0] ?? null)} />}</Field>
          <Field label="Evidence JSON">{props => <input {...props} type="file" accept=".json" onChange={event => setEvidence(event.target.files?.[0] ?? null)} />}</Field>
          <Button type="submit" icon={<Upload size={14} aria-hidden="true" />} disabled={!csv || !evidence} busy={importMutation.isPending}>
            Проверить и импортировать
          </Button>
        </form>
        {importMutation.isSuccess && <StatusBadge tone="ok">Реестр импортирован</StatusBadge>}
        {importMutation.error && <ErrorState error={importMutation.error} context="Импорт реестра" />}
      </Details>
      {!version && <p className="small muted">Реестр для этого набора еще не загружен.</p>}
      {state.isLoading && version && <LoadingState />}
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
                    Соответствие профиля
                  </th>
                  <th scope="col">Источник</th>
                </tr>
              </thead>
              <tbody>
                {shown.map(buyer => (
                  <tr key={buyer.buyer_id ?? buyer.name}>
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

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Ban, CheckCircle2, GitCompare, Pencil, Play, Plus, Save, Trash2, Undo2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import type { CutPlan, Dataset, DraftEdit, Material, Part, PlanComparison, Remnant, SolverConfig, ValidationResult } from '../../api/types';
import { formatAreaM2, formatDims, formatInt, formatMoney, formatPercent, formatSignedInt, formatSignedMoney } from '../../lib/format';
import { useAppStore } from '../../state/store';
import { Button, ConfirmDialog, Details, EmptyState, ErrorState, LoadingState, Metric, Panel, StaleNotice, StatusBadge, TableWrap } from '../../ui/kit';
import { isMutable } from '../shell/dataset';
import { JobPanel } from '../shell/JobPanel';
import { RequireDataset } from '../shell/RequireDataset';
import { useJob } from '../shell/useJob';
import { AddRemnantDialog, ConsumeDialog, MeasureDialog } from './RemnantDialogs';
import { SchemeEditor } from './SchemeEditor';
import { PlanInsights } from './PlanInsights';
import { OperationalDocument } from '../workplace/OperationalDocument';
import { LabelLookup } from './LabelLookup';
import { draftChanged, draftKey, effectivePlacements, useCuttingStore } from './draftStore';
import { PLAN_STATUS_LABEL, REMNANT_STATUS_LABEL, SEARCH_STATUS_LABEL, parseLocation, reasonLabel } from './labels';

export function CuttingPage() {
  return <RequireDataset>{dataset => <Cutting dataset={dataset} key={dataset.dataset_id} />}</RequireDataset>;
}

function Cutting({ dataset }: { dataset: Dataset }) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const storedPlanId = useAppStore(state => state.activePlanIds[dataset.dataset_id]);
  const setActivePlan = useAppStore(state => state.setActivePlan);
  const plans = useQuery({ queryKey: ['plans', dataset.dataset_id], queryFn: ({ signal }) => api.listPlans(dataset.dataset_id, signal) });
  const remnants = useQuery({ queryKey: ['remnants', dataset.dataset_id], queryFn: ({ signal }) => api.listRemnants(dataset.dataset_id, signal) });
  // Parts and materials come from C2's read-only solve-input snapshot (no separate list endpoints).
  const snapshot = useQuery({ queryKey: ['solve-input', dataset.dataset_id], queryFn: ({ signal }) => api.solveInput(dataset.dataset_id, signal), staleTime: 60_000 });
  const parts = { ...snapshot, data: snapshot.data?.parts };
  const materials = { ...snapshot, data: snapshot.data?.materials };

  const planSummary = plans.data?.find(plan => plan.plan_id === storedPlanId) ?? plans.data?.find(plan => plan.status === 'committed') ?? plans.data?.[0];
  const planId = planSummary?.plan_id ?? null;
  const plan = useQuery({
    queryKey: ['plan', dataset.dataset_id, planId],
    enabled: Boolean(planId),
    queryFn: ({ signal }) => api.getPlan(planId as string, dataset.dataset_id, signal),
  });

  const [jobId, setJobId] = useState<string | null>(null);
  const [tab, setTab] = useState<'parts' | 'remnants'>('remnants');
  const [addOpen, setAddOpen] = useState(false);
  const [compareWith, setCompareWith] = useState<string | null>(null);

  const partMap = useMemo(() => new Map((parts.data ?? []).map(part => [part.part_id, part])), [parts.data]);
  const materialMap = useMemo(() => new Map((materials.data ?? []).map(material => [material.material_id, material])), [materials.data]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Остатки и раскрой</p>
          <h1>Склад, схема и версии плана</h1>
          <p className="lead">Предпросмотр в браузере только подсказывает; окончательную допустимость и резерв решает сервер. Активный план не меняется до подтверждения.</p>
        </div>
        <div className="row">
          {isMutable(dataset) && (
            <Button icon={<Plus size={14} aria-hidden="true" />} onClick={() => setAddOpen(true)} disabled={!materials.data}>
              Добавить остаток
            </Button>
          )}
        </div>
      </header>

      <SolvePanel
        dataset={dataset}
        plan={plan.data ?? null}
        jobId={jobId}
        onJob={setJobId}
        onPlanReady={newPlanId => {
          queryClient.invalidateQueries({ queryKey: ['plans', dataset.dataset_id] });
          setCompareWith(newPlanId);
        }}
      />

      {plans.isLoading && <LoadingState label="Загружаем планы раскроя…" />}
      {plans.isError && <ErrorState error={plans.error} onRetry={() => plans.refetch()} context="Планы" />}
      {plans.data && plans.data.length === 0 && <EmptyState title="Планов раскроя пока нет">Запустите расчет выше: первый допустимый план появится до завершения полного поиска.</EmptyState>}
      {plans.data && plans.data.length > 0 && planSummary && (
        <Panel
          title="Версия плана"
          actions={
            <label className="inline-field">
              План
              <select aria-label="Версия плана" value={planSummary.plan_id} onChange={event => setActivePlan(dataset.dataset_id, event.target.value)}>
                {plans.data.map(item => (
                  <option key={item.plan_id} value={item.plan_id}>
                    {item.plan_id} · рев. {item.revision} · {PLAN_STATUS_LABEL[item.status] ?? item.status} · {formatPercent(item.coverage, 2)}
                  </option>
                ))}
              </select>
            </label>
          }
        >
          {plan.isLoading && <LoadingState label="Загружаем размещения…" />}
          {plan.isError && <ErrorState error={plan.error} onRetry={() => plan.refetch()} context="План" />}
          <LabelLookup datasetId={dataset.dataset_id} />
          {plan.data && <PlanMetrics plan={plan.data} />}
          {plan.data && <PlanInsights datasetId={dataset.dataset_id} planId={plan.data.plan_id} revision={plan.data.revision} />}
        </Panel>
      )}

      {compareWith && planId && compareWith !== planId && (
        <ComparePanel dataset={dataset} basePlanId={planId} candidatePlanId={compareWith} onAdopt={() => setActivePlan(dataset.dataset_id, compareWith)} onClose={() => setCompareWith(null)} />
      )}

      <div className="cutting-grid">
        <div className="stack">
          <div className="segmented" role="tablist" aria-label="Таблицы раскроя">
            <button role="tab" aria-selected={tab === 'remnants'} className={tab === 'remnants' ? 'active' : ''} onClick={() => setTab('remnants')}>
              Остатки ({remnants.data?.length ?? '…'})
            </button>
            <button role="tab" aria-selected={tab === 'parts'} className={tab === 'parts' ? 'active' : ''} onClick={() => setTab('parts')}>
              Детали заказов ({parts.data?.length ?? '…'})
            </button>
          </div>
          {tab === 'remnants' ? (
            <RemnantsTable dataset={dataset} remnants={remnants} plan={plan.data ?? null} materials={materialMap} />
          ) : (
            <PartsTable parts={parts} plan={plan.data ?? null} datasetId={dataset.dataset_id} />
          )}
        </div>
        <div className="stack">
          {plan.data && remnants.data && parts.data ? (
            <EditorPanel dataset={dataset} plan={plan.data} remnants={remnants.data} parts={partMap} materials={materialMap} />
          ) : (
            <Panel title="Схема">
              {(remnants.isError || parts.isError) && <ErrorState error={remnants.error ?? parts.error} onRetry={() => { remnants.refetch(); parts.refetch(); }} context="Данные раскроя" />}
              {!remnants.isError && !parts.isError && <EmptyState title="Выберите остаток">Схема и табличная альтернатива появятся здесь.</EmptyState>}
            </Panel>
          )}
        </div>
      </div>
      {materials.data && <AddRemnantDialog dataset={dataset} materials={materials.data} open={addOpen} onOpenChange={setAddOpen} />}
    </div>
  );
}

function PlanMetrics({ plan }: { plan: CutPlan }) {
  const m = plan.metrics;
  const newCount = plan.placements.filter(item => item.remnant_id === 'NEW').length;
  const stopReason = plan.stop_reason && plan.stop_reason !== 'completed' ? plan.stop_reason : null;
  return (
    <div className="stack">
      <div className="metrics-row">
        <Metric label="Покрытие площади" value={formatPercent(m.coverage, 4)} detail={`${formatAreaM2(m.covered_area_mm2)} из ${formatAreaM2(m.total_area_mm2)}`} />
        <Metric label="Оценка замещенного материала" value={formatMoney(m.replacement_value_tg, { fixed2: true })} detail="по ставкам materials.csv; не прибыль" />
        <Metric label="Полностью покрытые заказы" value={formatInt(m.fully_covered_orders)} />
        <Metric label="Детали NEW" value={formatInt(newCount)} detail="не покрыты остатками" />
        <Metric label="Свободные исходные куски" value={formatInt(plan.free_original_remnant_ids.length)} tone={plan.free_original_remnant_ids.length >= 5 ? 'ok' : 'warn'} detail="нужно ≥ 5 для карточек" />
        <Metric label="Ошибки / пропуски" value={`${m.invalid} / ${m.missing}`} tone={m.invalid === 0 && m.missing === 0 ? 'ok' : 'error'} />
      </div>
      <div className="row wrap">
        <StatusBadge tone={plan.status === 'committed' ? 'ok' : plan.status === 'invalid' ? 'error' : 'info'}>{PLAN_STATUS_LABEL[plan.status]}</StatusBadge>
        <StatusBadge tone={plan.search_status === 'limited' || plan.search_status === 'feasible' ? 'warn' : plan.search_status === 'infeasible' ? 'error' : 'ok'}>
          {SEARCH_STATUS_LABEL[plan.search_status]}
        </StatusBadge>
        <span className="small muted">
          <span className="mono">{plan.plan_id}</span> · ревизия {plan.revision}
          {stopReason && <> · остановка: {stopReason}</>}
          {plan.inventory_current === false && <> · склад изменился после расчета</>}
        </span>
      </div>
    </div>
  );
}

function SolvePanel({
  dataset,
  plan,
  jobId,
  onJob,
  onPlanReady,
}: {
  dataset: Dataset;
  plan: CutPlan | null;
  jobId: string | null;
  onJob: (id: string) => void;
  onPlanReady: (planId: string) => void;
}) {
  const { api } = useApi();
  const [profile, setProfile] = useState<NonNullable<SolverConfig['profile']>>('standard');
  const [mode, setMode] = useState<'keep' | 'replan'>('keep');
  const [minFree, setMinFree] = useState('5');
  const [key, setKey] = useState(newIdempotencyKey);
  const job = useJob(jobId);
  const solve = useMutation({
    mutationFn: () => {
      const budgets = { quick: 5, standard: 60, extended: 600 } as const;
      const excluded = plan ? useCuttingStore.getState().drafts[draftKey(dataset.dataset_id, plan.plan_id)]?.excluded ?? [] : [];
      return api.solve(
        {
          dataset_id: dataset.dataset_id,
          base_plan_id: plan?.plan_id ?? null,
          locks: (plan?.placements ?? []).filter(item => item.lock_kind !== 'none'),
          mode: mode === 'keep' ? 'keep_committed' : 'replan',
          excluded_remnant_ids: excluded,
          config: { profile, seed: 42, time_limit_seconds: budgets[profile], workers: 1, minimum_free_remnants: Number(minFree) || 0 },
        },
        key,
      );
    },
    onSuccess: created => {
      onJob(created.job_id);
      setKey(newIdempotencyKey());
    },
  });
  const ready = job.data?.state === 'completed' ? job.data.result_ref : job.data?.last_valid_result_ref;
  useEffect(() => {
    if (job.data?.state === 'completed') {
      const planId = job.data.result?.plan_id;
      if (typeof planId === 'string') onPlanReady(planId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.data?.state, job.data?.result_ref]);
  return (
    <Panel title="Расчет раскроя" subtitle="Тяжелый поиск выполняется в отдельном процессе; первый валидный план показывается сразу, более долгий поиск его улучшает.">
      <form
        className="row wrap align-end"
        onSubmit={event => {
          event.preventDefault();
          solve.mutate();
        }}
      >
        <label className="inline-field">
          Профиль
          <select value={profile} onChange={event => setProfile(event.target.value as NonNullable<SolverConfig['profile']>)}>
            <option value="quick">Быстрый подбор (~5 с)</option>
            <option value="standard">Стандартный (60 с)</option>
            <option value="extended">Расширенный конкурсный (600 с)</option>
          </select>
        </label>
        <label className="inline-field">
          Режим
          <select value={mode} onChange={event => setMode(event.target.value as 'keep' | 'replan')}>
            <option value="keep">Без перестройки: закрепить текущие размещения</option>
            <option value="replan">Полное перепланирование</option>
          </select>
        </label>
        <label className="inline-field">
          Мин. свободных кусков
          <input inputMode="numeric" value={minFree} onChange={event => setMinFree(event.target.value.replace(/\D/g, ''))} style={{ width: 80 }} />
        </label>
        <Button type="submit" variant="primary" icon={<Play size={14} aria-hidden="true" />} busy={solve.isPending}>
          Запустить расчет
        </Button>
      </form>
      {solve.error && <ErrorState error={solve.error} onRetry={() => solve.mutate()} context="Запуск расчета" />}
      {jobId && <JobPanel jobId={jobId} title="Поиск раскроя" />}
      {ready && job.data?.state !== 'completed' && <p className="small">Доступен последний валидный план: <span className="mono">{ready}</span></p>}
    </Panel>
  );
}

function RemnantsTable({
  dataset,
  remnants,
  plan,
  materials,
}: {
  dataset: Dataset;
  remnants: { data?: Remnant[]; isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown };
  plan: CutPlan | null;
  materials: Map<string, Material>;
}) {
  const { selectedRemnantId, select } = useCuttingStore();
  const [filter, setFilter] = useState({ text: '', material: '', status: '', usage: '' });
  const [measure, setMeasure] = useState<Remnant | null>(null);
  const [consume, setConsume] = useState<Remnant | null>(null);
  const draftId = plan ? draftKey(dataset.dataset_id, plan.plan_id) : '';
  const draft = useCuttingStore(state => state.drafts[draftId]);
  const toggleExcluded = useCuttingStore(state => state.toggleExcluded);
  const used = useMemo(() => {
    const count = new Map<string, number>();
    for (const placement of plan?.placements ?? []) if (placement.remnant_id !== 'NEW') count.set(placement.remnant_id, (count.get(placement.remnant_id) ?? 0) + 1);
    return count;
  }, [plan]);
  if (remnants.isLoading) return <LoadingState label="Загружаем склад…" />;
  if (remnants.isError) return <ErrorState error={remnants.error} onRetry={() => remnants.refetch()} context="Остатки" />;
  const list = (remnants.data ?? []).filter(item => {
    if (filter.text && !`${item.remnant_id} ${item.location_raw}`.toLowerCase().includes(filter.text.toLowerCase())) return false;
    if (filter.material && item.material_id !== filter.material) return false;
    if (filter.status && item.status !== filter.status) return false;
    if (filter.usage === 'used' && !used.has(item.remnant_id)) return false;
    if (filter.usage === 'free' && used.has(item.remnant_id)) return false;
    return true;
  });
  const materialIds = [...new Set((remnants.data ?? []).map(item => item.material_id))].sort();
  const mutable = isMutable(dataset);
  return (
    <Panel title="Остатки">
      <div className="filters compact">
        <label>
          Поиск
          <input type="search" value={filter.text} onChange={event => setFilter({ ...filter, text: event.target.value })} placeholder="ID или место" />
        </label>
        <label>
          Материал
          <select value={filter.material} onChange={event => setFilter({ ...filter, material: event.target.value })}>
            <option value="">Все</option>
            {materialIds.map(id => (
              <option key={id}>{id}</option>
            ))}
          </select>
        </label>
        <label>
          Статус
          <select value={filter.status} onChange={event => setFilter({ ...filter, status: event.target.value })}>
            <option value="">Все</option>
            {Object.entries(REMNANT_STATUS_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          В плане
          <select value={filter.usage} onChange={event => setFilter({ ...filter, usage: event.target.value })}>
            <option value="">Все</option>
            <option value="used">Используется</option>
            <option value="free">Свободен в плане</option>
          </select>
        </label>
      </div>
      {list.length === 0 ? (
        <EmptyState title="Нет остатков по фильтру" />
      ) : (
        <TableWrap label="Остатки склада" maxHeight={520}>
          <table className="table compact selectable">
            <thead>
              <tr>
                <th scope="col">ID</th>
                <th scope="col">Материал</th>
                <th scope="col">Размер</th>
                <th scope="col">Место</th>
                <th scope="col">Статус</th>
                <th scope="col" className="num">
                  Деталей
                </th>
                <th scope="col">Действия</th>
              </tr>
            </thead>
            <tbody>
              {list.map(item => {
                const location = parseLocation(item.location_raw);
                const excluded = draft?.excluded.includes(item.remnant_id);
                return (
                  <tr key={item.remnant_id} aria-selected={selectedRemnantId === item.remnant_id} className={excluded ? 'row-excluded' : undefined}>
                    <th scope="row">
                      <button className="link-btn mono" onClick={() => select(item.remnant_id)} aria-label={`Открыть схему ${item.remnant_id}`}>
                        {item.remnant_id}
                      </button>
                      {item.defect && <span className="small text-warn"> · дефект</span>}
                    </th>
                    <td>
                      <span className="mono">{item.material_id}</span>
                      {materials.get(item.material_id)?.tempered && <span className="small"> · калёное</span>}
                    </td>
                    <td>{formatDims(item.dimensions)}</td>
                    <td title={item.location_raw}>{location.rack ? `${location.rack}-${location.cell ?? '?'}` : item.location_raw}</td>
                    <td>
                      <StatusBadge tone={item.status === 'available' ? 'ok' : item.status === 'reserved' ? 'info' : 'neutral'}>{REMNANT_STATUS_LABEL[item.status ?? 'available']}</StatusBadge>
                    </td>
                    <td className="num">{used.get(item.remnant_id) ?? 0}</td>
                    <td className="actions-cell">
                      {plan && mutable && (
                        <Button
                          variant="ghost"
                          icon={excluded ? <Undo2 size={13} aria-hidden="true" /> : <Ban size={13} aria-hidden="true" />}
                          onClick={() => toggleExcluded(draftId, plan.plan_id, plan.revision, item.remnant_id)}
                          aria-label={excluded ? `Вернуть ${item.remnant_id}` : `Исключить ${item.remnant_id} в черновике`}
                        >
                          {excluded ? 'Вернуть' : 'Исключить'}
                        </Button>
                      )}
                      {mutable && item.status === 'available' && (
                        <Button variant="ghost" icon={<Pencil size={13} aria-hidden="true" />} onClick={() => setMeasure(item)} aria-label={`Замер ${item.remnant_id}`}>
                          Замер
                        </Button>
                      )}
                      {mutable && (item.status === 'reserved' || item.status === 'available') && (
                        <Button variant="ghost" icon={<Trash2 size={13} aria-hidden="true" />} onClick={() => setConsume(item)} aria-label={`Списать ${item.remnant_id}`}>
                          Списать
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
      )}
      {measure && <MeasureDialog dataset={dataset} remnant={measure} onClose={() => setMeasure(null)} />}
      {consume && <ConsumeDialog dataset={dataset} remnant={consume} onClose={() => setConsume(null)} />}
    </Panel>
  );
}

function PartsTable({ parts, plan, datasetId }: { parts: { data?: Part[]; isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown }; plan: CutPlan | null; datasetId: string }) {
  const { select } = useCuttingStore();
  const [filter, setFilter] = useState({ text: '', state: '' });
  const draft = useCuttingStore(state => (plan ? state.drafts[draftKey(datasetId, plan.plan_id)] : undefined));
  const placements = useMemo(() => new Map(effectivePlacements(plan?.placements ?? [], draft).map(item => [item.part_id, item])), [plan, draft]);
  if (parts.isLoading) return <LoadingState label="Загружаем детали…" />;
  if (parts.isError) return <ErrorState error={parts.error} onRetry={() => parts.refetch()} context="Детали" />;
  const list = (parts.data ?? []).filter(part => {
    const placement = placements.get(part.part_id);
    if (filter.text && !`${part.part_id} ${part.order_id} ${part.material_id} ${part.product_type}`.toLowerCase().includes(filter.text.toLowerCase())) return false;
    if (filter.state === 'new' && placement?.remnant_id !== 'NEW') return false;
    if (filter.state === 'placed' && (!placement || placement.remnant_id === 'NEW')) return false;
    return true;
  });
  return (
    <Panel title="Детали заказов">
      <div className="filters compact">
        <label>
          Поиск
          <input type="search" value={filter.text} onChange={event => setFilter({ ...filter, text: event.target.value })} placeholder="деталь, заказ, материал" />
        </label>
        <label>
          Состояние
          <select value={filter.state} onChange={event => setFilter({ ...filter, state: event.target.value })}>
            <option value="">Все</option>
            <option value="placed">На остатке</option>
            <option value="new">NEW</option>
          </select>
        </label>
      </div>
      {list.length === 0 ? (
        <EmptyState title="Нет деталей по фильтру" />
      ) : (
        <TableWrap label="Детали заказов" maxHeight={520}>
          <table className="table compact">
            <thead>
              <tr>
                <th scope="col">Деталь</th>
                <th scope="col">Заказ</th>
                <th scope="col">Материал</th>
                <th scope="col">Размер</th>
                <th scope="col">Тип</th>
                <th scope="col">Размещение</th>
              </tr>
            </thead>
            <tbody>
              {list.map(part => {
                const placement = placements.get(part.part_id);
                const isNew = !placement || placement.remnant_id === 'NEW';
                return (
                  <tr key={part.part_id}>
                    <th scope="row" className="mono">
                      {part.part_id}
                      {part.premium && <span className="small"> · премиум</span>}
                    </th>
                    <td className="mono">{part.order_id}</td>
                    <td className="mono">{part.material_id}</td>
                    <td>{formatDims(part.dimensions)}</td>
                    <td>{part.product_type}</td>
                    <td>
                      {isNew ? (
                        <span className="small">
                          <StatusBadge tone="neutral">NEW</StatusBadge> {(() => {
                            const code = plan?.metrics.new_reasons?.[part.part_id] ?? plan?.new_reasons?.[part.part_id];
                            return code ? reasonLabel(code) : 'причина не передана';
                          })()}
                        </span>
                      ) : (
                        <button className="link-btn mono" onClick={() => select(placement!.remnant_id, part.part_id)}>
                          {placement!.remnant_id} ({placement!.x_mm}, {placement!.y_mm}){placement!.rot ? ' ⟲' : ''}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
      )}
    </Panel>
  );
}

function EditorPanel({ dataset, plan, remnants, parts, materials }: { dataset: Dataset; plan: CutPlan; remnants: Remnant[]; parts: Map<string, Part>; materials: Map<string, Material> }) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const setActivePlan = useAppStore(state => state.setActivePlan);
  const { selectedRemnantId } = useCuttingStore();
  const key = draftKey(dataset.dataset_id, plan.plan_id);
  const draft = useCuttingStore(state => state.drafts[key]);
  const setOverride = useCuttingStore(state => state.setOverride);
  const discard = useCuttingStore(state => state.discard);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [savedDraft, setSavedDraft] = useState<CutPlan | null>(null);
  const [commitOpen, setCommitOpen] = useState(false);
  const [commitKey, setCommitKey] = useState(newIdempotencyKey);
  const effective = useMemo(() => effectivePlacements(plan.placements, draft), [plan.placements, draft]);
  const remnant = remnants.find(item => item.remnant_id === selectedRemnantId);
  const changed = draftChanged(draft);
  const outdatedDraft = draft && draft.baseRevision !== plan.revision;
  const mutable = isMutable(dataset);

  const newlyNew = useMemo(() => {
    const before = new Map(plan.placements.map(item => [item.part_id, item.remnant_id]));
    return effective.filter(item => item.remnant_id === 'NEW' && before.get(item.part_id) !== 'NEW');
  }, [effective, plan.placements]);
  /** Preliminary geometric delta (integer mm²). Money delta comes only from the server comparison. */
  const areaDelta = useMemo(() => {
    let delta = 0;
    const before = new Map(plan.placements.map(item => [item.part_id, item.remnant_id]));
    for (const item of effective) {
      const part = parts.get(item.part_id);
      if (!part) continue;
      const area = part.dimensions.length_mm * part.dimensions.width_mm;
      const was = before.get(item.part_id) !== 'NEW';
      const now = item.remnant_id !== 'NEW';
      if (was && !now) delta -= area;
      if (!was && now) delta += area;
    }
    return delta;
  }, [effective, plan.placements, parts]);

  /** C2 draft = list of edits against base_revision; the server returns the new revision and its validation. */
  const edits = useMemo<DraftEdit[]>(() => {
    const before = new Map(plan.placements.map(item => [item.part_id, item]));
    const list: DraftEdit[] = [];
    for (const item of effective) {
      const old = before.get(item.part_id);
      if (!old) continue;
      const moved = old.remnant_id !== item.remnant_id || old.x_mm !== item.x_mm || old.y_mm !== item.y_mm || old.rot !== item.rot;
      if (moved) {
        list.push(item.remnant_id === 'NEW' ? { part_id: item.part_id, action: 'unplace' } : { part_id: item.part_id, action: 'move', remnant_id: item.remnant_id, x_mm: item.x_mm, y_mm: item.y_mm, rot: item.rot });
      }
      if (old.lock_kind !== item.lock_kind && item.remnant_id !== 'NEW') {
        list.push(item.lock_kind === 'none' ? { part_id: item.part_id, action: 'unlock' } : { part_id: item.part_id, action: 'lock', lock_kind: item.lock_kind });
      }
    }
    return list;
  }, [effective, plan.placements]);

  const save = useMutation({
    mutationFn: () => api.draftPlan(plan.plan_id, { dataset_id: dataset.dataset_id, base_revision: plan.revision, edits }),
    onSuccess: result => {
      // Continue on the new server revision (draft chain); the committed plan stays the active one.
      discard(key);
      setSavedDraft(null);
      setValidation(result.validation);
      queryClient.setQueryData(['plan', dataset.dataset_id, result.plan.plan_id], result.plan);
      setActivePlan(dataset.dataset_id, result.plan.plan_id);
      setCommitKey(newIdempotencyKey());
      queryClient.invalidateQueries({ queryKey: ['plans', dataset.dataset_id] });
    },
  });
  const commit = useMutation({
    mutationFn: (target: CutPlan) => {
      const used = new Set(target.placements.filter(item => item.remnant_id !== 'NEW').map(item => item.remnant_id));
      const expected = Object.fromEntries(remnants.filter(item => used.has(item.remnant_id)).map(item => [item.remnant_id, item.version ?? 0]));
      return api.commitPlan(target.plan_id, { dataset_id: dataset.dataset_id, plan_revision: target.revision, expected_remnant_versions: expected, owner_context: 'ui:cutting-workspace' }, commitKey);
    },
    onSuccess: committed => {
      setCommitOpen(false);
      discard(key);
      setSavedDraft(null);
      setValidation(null);
      setActivePlan(dataset.dataset_id, committed.plan.plan_id);
      queryClient.invalidateQueries({ queryKey: ['plans', dataset.dataset_id] });
      queryClient.invalidateQueries({ queryKey: ['remnants', dataset.dataset_id] });
      queryClient.invalidateQueries({ queryKey: ['sale-cards', dataset.dataset_id] });
    },
    onError: () => {
      setCommitKey(newIdempotencyKey());
      queryClient.invalidateQueries({ queryKey: ['remnants', dataset.dataset_id] });
    },
  });

  const invalidIds = new Set([...(validation?.invalid_part_ids ?? [])]);
  const onRemnant = remnant ? effective.filter(item => item.remnant_id === remnant.remnant_id) : [];
  const sameMaterial = remnant ? remnants.filter(item => item.material_id === remnant.material_id && item.status === 'available') : [];
  const commitTarget = savedDraft && validation?.valid ? savedDraft : plan.status === 'validated' ? plan : null;

  return (
    <Panel
      title="Схема и черновик"
      subtitle={mutable ? 'Перетаскивание, стрелки, поворот, точные x/y и закрепления. Изменения — локальный черновик.' : 'Только просмотр: изменения возможны в рабочей копии.'}
    >
      {outdatedDraft && <StaleNotice>Черновик создан для ревизии {draft?.baseRevision}, а текущая ревизия {plan.revision}. Отмените черновик и начните заново.</StaleNotice>}
      {(changed || savedDraft) && (
        <div className="draft-bar" role="status">
          <div>
            <strong>Черновик</strong> · изменено размещений: {Object.keys(draft?.overrides ?? {}).length} · исключено кусков: {draft?.excluded.length ?? 0}
            {newlyNew.length > 0 && (
              <div className="small">
                Новые NEW: <span className="mono">{newlyNew.map(item => item.part_id).join(', ')}</span>
              </div>
            )}
            <div className="small">
              Изменение покрытой площади (предварительно): <b>{formatSignedInt(areaDelta)} мм²</b> ({formatAreaM2(areaDelta)}). Оценку в тенге и затронутые предложения/карточки показывает серверное сравнение.
            </div>
          </div>
          <div className="row wrap">
            <Button variant="ghost" icon={<Undo2 size={14} aria-hidden="true" />} onClick={() => { discard(key); setValidation(null); setSavedDraft(null); }}>
              Отменить черновик
            </Button>
            {mutable && (
              <Button icon={<Save size={14} aria-hidden="true" />} onClick={() => save.mutate()} busy={save.isPending} disabled={edits.length === 0 || Boolean(outdatedDraft)}>
                Сохранить и проверить
              </Button>
            )}
            {commitTarget && mutable && (
              <Button variant="primary" icon={<CheckCircle2 size={14} aria-hidden="true" />} onClick={() => setCommitOpen(true)}>
                Подтвердить ревизию {commitTarget.revision}
              </Button>
            )}
          </div>
        </div>
      )}
      {!changed && !savedDraft && plan.status === 'validated' && mutable && (
        <div className="draft-bar" role="status">
          <div>
            <strong>Ревизия {plan.revision} проверена сервером, но еще не действующая.</strong>
            <div className="small">Действующий план меняется только после подтверждения с проверкой версий кусков.</div>
          </div>
          <Button variant="primary" icon={<CheckCircle2 size={14} aria-hidden="true" />} onClick={() => setCommitOpen(true)}>
            Подтвердить ревизию {plan.revision}
          </Button>
        </div>
      )}
      {(draft?.excluded ?? []).map(remnantId => (
        <ExclusionImpact key={remnantId} dataset={dataset} planId={plan.plan_id} remnantId={remnantId} />
      ))}
      {save.error && <ErrorState error={save.error} onRetry={() => save.mutate()} context="Сохранение черновика" />}
      {validation && (
        <div className={`state ${validation.valid ? 'state-ok' : 'state-error'}`} role="status">
          <div>
            <strong>{validation.valid ? 'Сервер: черновик допустим' : 'Сервер: черновик недопустим — активный план не изменен'}</strong>
            {(validation.issues?.length ? validation.issues.map(issue => issue.message_ru) : validation.errors).length > 0 && (
              <ul className="plain small">
                {(validation.issues?.length ? validation.issues.map(issue => `${issue.part_id ? `${issue.part_id}: ` : ''}${issue.message_ru}`) : validation.errors)
                  .slice(0, 12)
                  .map((error, index) => (
                    <li key={index}>{error}</li>
                  ))}
              </ul>
            )}
            {validation.missing_part_ids.length > 0 && <p className="small">Пропущены: {validation.missing_part_ids.join(', ')}</p>}
          </div>
        </div>
      )}
      {remnant && dataset.mode === 'workspace' && <OperationalDocument datasetId={dataset.dataset_id} kind="piece" subjectId={remnant.remnant_id} version={remnant.version ?? 0} />}
      {!remnant ? (
        <EmptyState title="Выберите остаток в таблице">Откроется схема с размерами, краем 5 мм и табличной альтернативой.</EmptyState>
      ) : (
        <SchemeEditor
          remnant={remnant}
          tempered={Boolean(materials.get(remnant.material_id)?.tempered ?? remnant.tempered)}
          placements={onRemnant}
          parts={parts}
          invalidPartIds={invalidIds}
          editable={mutable && !outdatedDraft}
          candidateRemnants={sameMaterial}
          onChange={placement => setOverride(key, plan.plan_id, plan.revision, placement)}
        />
      )}
      {commitTarget && (
        <ConfirmDialog
          open={commitOpen}
          onOpenChange={open => {
            setCommitOpen(open);
            if (!open) commit.reset();
          }}
          title="Подтвердить план и резервы"
          action={`Ревизия ${commitTarget.revision} плана ${commitTarget.plan_id} станет действующей; все использованные целые куски будут зарезервированы одной транзакцией. При изменении версии любого куска сервер вернет конфликт.`}
          affected={[
            { label: 'Покрытие', value: formatPercent(commitTarget.metrics.coverage, 4) },
            { label: 'Используемых кусков', value: String(new Set(commitTarget.placements.filter(item => item.remnant_id !== 'NEW').map(item => item.remnant_id)).size) },
            { label: 'Деталей NEW', value: String(commitTarget.placements.filter(item => item.remnant_id === 'NEW').length) },
          ]}
          confirmLabel="Подтвердить план"
          onConfirm={() => commit.mutate(commitTarget)}
          busy={commit.isPending}
          error={commit.error}
        />
      )}
    </Panel>
  );
}

function ComparePanel({ dataset, basePlanId, candidatePlanId, onAdopt, onClose }: { dataset: Dataset; basePlanId: string; candidatePlanId: string; onAdopt: () => void; onClose: () => void }) {
  const { api } = useApi();
  const compare = useQuery({
    queryKey: ['compare', dataset.dataset_id, basePlanId, candidatePlanId],
    queryFn: () => api.comparePlans({ dataset_id: dataset.dataset_id, base: { plan_id: basePlanId }, candidate: { plan_id: candidatePlanId } }),
  });
  const data: PlanComparison | undefined = compare.data;
  return (
    <Panel
      title="Сравнение версий"
      subtitle="Новый план не применяется автоматически: действующий остается активным до явного выбора и подтверждения."
      actions={
        <div className="row">
          <Button variant="ghost" onClick={onClose}>
            Закрыть
          </Button>
          <Button icon={<GitCompare size={14} aria-hidden="true" />} onClick={onAdopt}>
            Открыть новую версию
          </Button>
        </div>
      }
    >
      {compare.isLoading && <LoadingState label="Сравниваем…" />}
      {compare.isError && <ErrorState error={compare.error} onRetry={() => compare.refetch()} context="Сравнение" />}
      {data && (
        <div className="stack">
          <div className="metrics-row">
            <Metric label="Δ покрытой площади" value={`${formatSignedInt(data.delta_covered_area_mm2)} мм²`} detail={formatAreaM2(data.delta_covered_area_mm2)} tone={data.delta_covered_area_mm2 >= 0 ? 'ok' : 'warn'} />
            <Metric label="Δ оценки материала" value={formatSignedMoney(data.delta_value_tg)} />
            <Metric label="Δ полностью покрытых заказов" value={formatSignedInt(data.delta_fully_covered_orders)} />
            <Metric label="Δ покрытия" value={`${data.delta_coverage >= 0 ? '+' : '−'}${formatPercent(Math.abs(data.delta_coverage), 3)}`} />
            <Metric label="Δ свободных исходных кусков" value={formatSignedInt(data.delta_free_original_remnants)} tone={data.delta_free_original_remnants < 0 ? 'warn' : undefined} />
          </div>
          <Details summary={`Детали, ставшие NEW (${data.newly_new_part_ids.length}) и покрытые заново (${data.newly_covered_part_ids.length}); изменений размещения: ${data.changes.filter(item => item.kind !== 'unchanged').length}`}>
            <p className="small mono">NEW: {data.newly_new_part_ids.join(', ') || '—'}</p>
            <p className="small mono">Покрыты: {data.newly_covered_part_ids.join(', ') || '—'}</p>
          </Details>
          {data.affected_reserved_remnant_ids.length > 0 && (
            <div className="state state-warn">
              <div>
                <strong>Затронуты зарезервированные куски — нужно отдельное подтверждение</strong>
                <p className="small mono">{data.affected_reserved_remnant_ids.join(', ')}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

/** Server-side consequences of excluding one remnant (C2 /cutting/impact): the active plan is not changed. */
function ExclusionImpact({ dataset, planId, remnantId }: { dataset: Dataset; planId: string; remnantId: string }) {
  const { api } = useApi();
  const impact = useQuery({
    queryKey: ['impact', dataset.dataset_id, planId, remnantId],
    queryFn: () => api.impact({ dataset_id: dataset.dataset_id, remnant_id: remnantId, change: 'exclude', plan_id: planId }),
  });
  if (impact.isLoading) return <LoadingState label={`Считаем последствия исключения ${remnantId}…`} />;
  if (impact.isError) return <ErrorState error={impact.error} onRetry={() => impact.refetch()} context={`Последствия исключения ${remnantId}`} />;
  const data = impact.data!;
  return (
    <div className="state state-info" role="status">
      <div>
        <strong>Исключение {remnantId}: прогноз сервера</strong>
        <p className="small">
          Затронуто деталей: {data.affected_part_ids.length} · новые NEW: <span className="mono">{data.new_part_ids.join(', ') || '—'}</span> · Δ площади{' '}
          {formatSignedInt(data.delta_covered_area_mm2)} мм² · Δ оценки {formatSignedMoney(data.delta_value_tg)}
        </p>
        {(data.affected_reservation_ids.length > 0 || data.affected_order_ids.length > 0) && (
          <p className="small">
            Резервы: {data.affected_reservation_ids.join(', ') || '—'} · заказы: {data.affected_order_ids.join(', ') || '—'}
          </p>
        )}
        {data.note_ru && <p className="small muted">{data.note_ru}</p>}
        <p className="small muted">Действующий план не изменен. Для нового размещения запустите расчет: исключенные куски передаются в solver.</p>
      </div>
    </div>
  );
}

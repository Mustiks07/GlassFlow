import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import { newIdempotencyKey } from '../../api/client';
import type { Dataset } from '../../api/types';
import { Button, Details, ErrorState, Panel } from '../../ui/kit';
import { formatMoney, formatDateTime } from '../../lib/format';
import { LaborPanel } from './LaborPanel';

type Scenario = components['schemas']['EconomicsScenario'];
type Assumptions = components['schemas']['EconomicAssumptions'];
type Source = components['schemas']['EconomicSource'];
type Study = components['schemas']['LaborStudyView'];
const MONEY = [
  ['monthly_operations', 'Операций в месяц'], ['monthly_dataset_multiplier', 'Наборов заказов в месяц'],
  ['hourly_rate_tg', 'Стоимость часа, ₸'], ['material_use_fraction', 'Доля использования прироста, 0–1'],
  ['ai_monthly_tg', 'ИИ в месяц, ₸'], ['hosting_monthly_tg', 'Хостинг в месяц, ₸'],
  ['support_monthly_tg', 'Поддержка в месяц, ₸'], ['implementation_tg', 'Разовое внедрение, ₸'],
] as const;
const BASIS = [
  ['hourly_rate_basis', 'Основание стоимости часа'], ['monthly_volume_basis', 'Источник месячного объёма'],
  ['ai_cost_basis', 'Основание расходов на ИИ, хостинг и поддержку'],
  ['implementation_basis', 'Основание стоимости внедрения'], ['material_use_basis', 'Основание доли использования материала'],
] as const;

export function EconomicsWizard({ dataset }: { dataset: Dataset }) {
  const { client } = useApi();
  const [name, setName] = useState('Сценарий внедрения');
  const [baseline, setBaseline] = useState('');
  const [final, setFinal] = useState('');
  const [studyId, setStudyId] = useState('');
  const [assumptions, setAssumptions] = useState<Partial<Assumptions>>({});
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const query = { dataset_id: dataset.dataset_id };
  const sources = useQuery({ queryKey: ['economics-sources', dataset.dataset_id], queryFn: () => client.get<components['schemas']['EconomicSources']>('/economics/scenarios/sources', { query }) });
  const studies = useQuery({ queryKey: ['labor-studies', dataset.dataset_id], queryFn: () => client.get<Study[]>('/labor-studies', { query }) });
  const saved = useQuery({ queryKey: ['economics-scenarios', dataset.dataset_id], queryFn: () => client.get<Scenario[]>('/economics/scenarios', { query }) });
  const selectedBase = sources.data?.results.find(r => r.reference === baseline);
  const selectedFinal = sources.data?.results.find(r => r.reference === final);
  const study = studies.data?.find(s => s.study_id === studyId);
  const comparable = Boolean(selectedBase && selectedFinal && baseline !== final && selectedBase.comparison_key === selectedFinal.comparison_key);
  const complete = [...MONEY, ...BASIS].every(([field]) => String(assumptions[field] ?? '').trim());
  function update(field: keyof Assumptions, value: string) { setAssumptions(a => ({ ...a, [field]: value })); setKey(newIdempotencyKey()); }
  async function calculate() {
    setBusy(true); setError(null);
    try {
      const value = await client.post<Scenario>('/economics/scenarios/wizard', {
        dataset_id: dataset.dataset_id, name, baseline_ref: baseline, final_ref: final,
        study_id: studyId, study_version: study!.version, assumptions,
      }, { idempotencyKey: key });
      setScenario(value); setKey(newIdempotencyKey()); await saved.refetch();
    } catch (e) { setError(e); await studies.refetch(); await sources.refetch(); } finally { setBusy(false); }
  }
  const options = (rows: Source[]) => rows.map((r, index) => <option key={r.reference} value={r.reference}>Результат {index + 1}: {r.label} · {r.created_at ? formatDateTime(r.created_at) : 'дата не записана'} · {formatMoney(r.material_value_tg)}</option>);
  return <div className="stack"><LaborPanel dataset={dataset} onExport={value => { void studies.refetch(); setStudyId(value.study_id); setKey(newIdempotencyKey()); }} />
    <Panel title="Мастер экономики" subtitle="Реальные результаты раскроя → подтверждённые трудозамеры → допущения → расчёт и PDF. Формула общая для экрана и документа.">
      <div className="stack">
        <label>Сохранённые сценарии<select aria-label="Сохранённые сценарии" value={scenario?.scenario_id ?? ''} onChange={e => setScenario(saved.data?.find(s => s.scenario_id === e.target.value) ?? null)}><option value="">Новый сценарий</option>{saved.data?.map(s => <option key={s.scenario_id} value={s.scenario_id}>{s.name} · {formatDateTime(s.created_at)} · версия {s.version}</option>)}</select></label>
        <h3>1. Сопоставимые результаты раскроя</h3>
        {sources.data?.warnings?.map((warning, index) => <p role="alert" key={index}>{warning}</p>)}
        <Button onClick={() => { void sources.refetch(); void studies.refetch(); }}>Обновить результаты и замеры</Button>
        {!sources.isLoading && !sources.data?.results.length && <p>Сначала выполните два расчёта на одинаковых исходных данных. Можно выбрать планы рабочей копии или принятые результаты прогонов исходного набора.</p>}
        <label>Результат для сравнения<select aria-label="Результат для сравнения" value={baseline} onChange={e => { setBaseline(e.target.value); setFinal(''); setKey(newIdempotencyKey()); }}><option value="">Выберите исходный результат</option>{options(sources.data?.results ?? [])}</select></label>
        <label>Итоговый результат<select aria-label="Итоговый результат" value={final} onChange={e => { setFinal(e.target.value); setKey(newIdempotencyKey()); }}><option value="">Выберите сопоставимый результат</option>{options((sources.data?.results ?? []).filter(r => r.reference !== baseline && r.comparison_key === selectedBase?.comparison_key))}</select></label>
        {selectedBase && selectedFinal && <p>Оценка материала: {formatMoney(selectedBase.material_value_tg)} → {formatMoney(selectedFinal.material_value_tg)}. Отрицательный результат сохраняется; это не выручка и не прибыль.</p>}
        <h3>2. Подтверждённые парные трудозамеры</h3>
        <label>Протокол измерений<select aria-label="Протокол измерений" value={studyId} onChange={e => { setStudyId(e.target.value); setKey(newIdempotencyKey()); }}><option value="">Выберите протокол</option>{studies.data?.map(s => <option key={s.study_id} value={s.study_id} disabled={!s.export_ready}>{s.name} · готово {s.ready_pair_count} пар{s.export_ready ? '' : ' · требуется завершить измерения'}</option>)}</select></label>
        <p>Нужно минимум десять разных пар и оба порядка выполнения. Таймер сам по себе не подтверждает человеческий труд.</p>
        <h3>3. Допущения и источники</h3>
        <label>Название сценария<input value={name} onChange={e => setName(e.target.value)} /></label>
        <div className="form-grid">{MONEY.map(([field, label]) => <label key={field}>{label}<input type="number" min="0" step="any" value={assumptions[field] ?? ''} onChange={e => update(field, e.target.value)} /></label>)}</div>
        {BASIS.map(([field, label]) => <label key={field}>{label}<textarea value={assumptions[field] ?? ''} onChange={e => update(field, e.target.value)} /></label>)}
        <p className="small muted">Расходы указываются явно, включая обоснование нулей. Потенциальные продажи не прибавляются к замещению материала.</p>
        <Button variant="primary" busy={busy} disabled={!comparable || !study?.export_ready || !complete || !name.trim()} onClick={calculate}>Рассчитать сценарий</Button>
        {scenario && <><h3>4. Результат</h3><p>{scenario.name} · версия {scenario.version}. Сценарный расчёт; конкурсная записка требует независимой проверки измерений и источников.</p>
          <dl className="facts"><dt>Месячный эффект материала</dt><dd>{formatMoney(scenario.results.material_delta_tg)}</dd><dt>Эффект активного труда</dt><dd>{formatMoney(scenario.results.labor_effect_tg)}</dd><dt>Расходы</dt><dd>{formatMoney(scenario.results.monthly_costs_tg)}</dd><dt>Чистый сценарный эффект</dt><dd>{formatMoney(scenario.results.scenario_net_effect_tg)}</dd><dt>Окупаемость</dt><dd>{scenario.results.payback_months == null ? 'Не достигается в этом сценарии' : `${Number(scenario.results.payback_months).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} мес.`}</dd></dl>
          <a className="btn btn-secondary" href={`/api/v1/economics/scenarios/${scenario.scenario_id}/pdf?dataset_id=${dataset.dataset_id}&version=${scenario.version}`} download>Скачать PDF этой версии</a>
          <Details summary="Источники и допущения сценария"><pre className="pre">{JSON.stringify(scenario.inputs, null, 2)}</pre></Details></>}
        {(error ?? sources.error ?? studies.error ?? saved.error) != null && <ErrorState error={error ?? sources.error ?? studies.error ?? saved.error} />}
      </div>
    </Panel></div>;
}

import { useState } from 'react';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import { newIdempotencyKey } from '../../api/client';
import type { Dataset } from '../../api/types';
import { Button, ErrorState, Panel } from '../../ui/kit';
import { formatMoney } from '../../lib/format';

type Inputs = components['schemas']['EconomicInputs'];
type Scenario = components['schemas']['EconomicsScenario'];
const FIELDS = [
  ['monthly_operations', 'Операций в месяц'], ['monthly_dataset_multiplier', 'Наборов заказов в месяц'],
  ['hourly_rate_tg', 'Стоимость часа, ₸'], ['material_use_fraction', 'Доля использования прироста, 0–1'],
  ['ai_monthly_tg', 'AI в месяц, ₸'], ['hosting_monthly_tg', 'Хостинг в месяц, ₸'],
  ['support_monthly_tg', 'Поддержка в месяц, ₸'], ['implementation_tg', 'Разовое внедрение, ₸'],
] as const;

export function EconomicsPanel({ dataset }: { dataset: Dataset }) {
  const { client } = useApi();
  const [inputs, setInputs] = useState<Inputs | null>(null);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [scenarioId, setScenarioId] = useState('');
  const [name, setName] = useState('Сценарий внедрения');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  async function calculate() {
    setBusy(true); setError(null);
    try {
      const value = scenario
        ? (await client.request<Scenario>('PUT', `/economics/scenarios/${scenario.scenario_id}`,
            { body: { dataset_id: dataset.dataset_id, expected_version: scenario.version, inputs }, idempotencyKey: key })).data
        : await client.post<Scenario>('/economics/scenarios', { dataset_id: dataset.dataset_id, name, inputs }, { idempotencyKey: key });
      setScenario(value); setScenarioId(value.scenario_id); setKey(newIdempotencyKey());
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <Panel title="Экономика внедрения" subtitle="Экран и PDF используют один серверный расчет. Оценка материала, подтвержденный расход и выручка разделены.">
    <div className="stack">
      <p>Для расчета нужны минимум 10 пар настоящих трудозамеров, ссылки на исходные результаты раскроя и основания ставок. Время ответа менеджера не является трудозатратами.</p>
      <label>Протокол замеров и исходных оценок <input type="file" accept=".json" onChange={async e => {
        const file = e.target.files?.[0]; if (!file) return;
        try { const value = JSON.parse(await file.text()); setInputs(value.inputs ?? value); setScenario(null); setKey(newIdempotencyKey()); setError(null); }
        catch (err) { setError(err); }
      }} /></label>
      <p className="small muted">В протоколе укажите начало и конец каждой операции, активное время, ошибки, оператора и ссылки на результаты. Неполные измерения будут отклонены; отсутствующие значения не заменяются нулями.</p>
      <label>Открыть сохраненный сценарий <input value={scenarioId} onChange={e => setScenarioId(e.target.value)} /></label>
      <Button disabled={!scenarioId} onClick={async () => {
        try { const value = await client.get<Scenario>(`/economics/scenarios/${scenarioId}`, { query: { dataset_id: dataset.dataset_id } }); setScenario(value); setInputs(value.inputs); setName(value.name); }
        catch (e) { setError(e); }
      }}>Открыть сценарий</Button>
      {inputs && <>
        <label>Название сценария <input value={name} onChange={e => setName(e.target.value)} /></label>
        <p>Протокол: {inputs.measurement_status === 'synthetic' ? 'СИНТЕТИЧЕСКИЙ — не конкурсный результат' : 'предоставленные замеры'} · задач: {inputs.labor_studies?.length ?? 0}</p>
        <div className="row wrap">{FIELDS.map(([field, label]) => <label key={field}>{label}<input type="number" min="0" step="any" value={inputs[field] ?? ''} onChange={e => { setInputs({ ...inputs, [field]: e.target.value }); setKey(newIdempotencyKey()); }} /></label>)}</div>
        <Button variant="primary" busy={busy} onClick={calculate}>Рассчитать сценарий</Button>
      </>}
      {scenario && <>
        <p>Версия {scenario.version} · {scenario.formula_version}. Сценарный расчет, не финальная конкурсная записка.</p>
        <dl className="facts"><dt>Прирост оценки материала за набор</dt><dd>{formatMoney(scenario.results.planned_material_delta_tg)}</dd>
          <dt>Месячный эффект материала с учетом доли</dt><dd>{formatMoney(scenario.results.material_delta_tg)}</dd>
          <dt>Труд</dt><dd>{formatMoney(scenario.results.labor_effect_tg)}</dd><dt>Расходы</dt><dd>{formatMoney(scenario.results.monthly_costs_tg)}</dd>
          <dt>Чистый сценарный эффект</dt><dd>{formatMoney(scenario.results.scenario_net_effect_tg)}</dd><dt>Окупаемость</dt><dd>{scenario.results.payback_months == null ? 'Не достигается в этом сценарии' : `${scenario.results.payback_months} мес.`}</dd>
          <dt>Диапазон допущений</dt><dd>{formatMoney(scenario.results.net_range_low_tg)} – {formatMoney(scenario.results.net_range_high_tg)}</dd></dl>
        <a className="btn btn-secondary" href={`/api/v1/economics/scenarios/${scenario.scenario_id}/pdf?dataset_id=${dataset.dataset_id}&version=${scenario.version}`} download>Скачать PDF этой версии</a>
      </>}
      {error != null && <ErrorState error={error} />}
    </div>
  </Panel>;
}

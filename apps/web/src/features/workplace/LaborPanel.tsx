import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import { newIdempotencyKey } from '../../api/client';
import type { Dataset } from '../../api/types';
import { Button, ErrorState, Panel } from '../../ui/kit';

type Study = components['schemas']['LaborStudyView'];
type Measurement = components['schemas']['LaborMeasurement'];
type Export = components['schemas']['LaborStudyExport'];
const METHOD = { manual: 'Вручную', app: 'В GlassFlow' };
const STATE = { running: 'Идёт', paused: 'Пауза', finished: 'Завершено, нужно подтверждение', attested: 'Активное время подтверждено' };
const PAIR_REASON: Record<string, string> = {
  PAIR_INCOMPLETE: 'Нужно выполнить задачу обоими способами',
  PAIR_INPUT_MISMATCH: 'Различаются задача, входы, оператор или порядок способов',
  HUMAN_ATTESTATION_REQUIRED: 'Человек должен подтвердить активное время обоих выполнений',
};

export function LaborPanel({ dataset, onExport }: { dataset: Dataset; onExport: (value: Export) => void }) {
  const { client } = useApi();
  const studies = useQuery({ queryKey: ['labor-studies', dataset.dataset_id],
    queryFn: () => client.get<Study[]>('/labor-studies', { query: { dataset_id: dataset.dataset_id } }), staleTime: 0 });
  const [study, setStudy] = useState<Study | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [name, setName] = useState('Парные измерения работы');
  const [operator, setOperator] = useState('');
  const [observer, setObserver] = useState('');
  const [protocol, setProtocol] = useState('Один оператор выполняет одну и ту же задачу вручную и в приложении. Содержание задачи одинаковое; порядок способов чередуется. Ошибки и переделки учитываются.');
  const [start, setStart] = useState('Оператор начинает читать заранее подготовленный запрос.');
  const [end, setEnd] = useState('Проверенный результат сохранён, включая исправления.');
  const [pair, setPair] = useState('');
  const [task, setTask] = useState('');
  const [inputRef, setInputRef] = useState('');
  const [inputText, setInputText] = useState('');
  const [method, setMethod] = useState<'manual' | 'app'>('manual');
  const [order, setOrder] = useState<'manual_first' | 'app_first'>('manual_first');
  const [requestKey, setRequestKey] = useState(newIdempotencyKey);
  const writable = dataset.mode === 'workspace';

  async function command(path: string, body: unknown) {
    setBusy(true); setError(null);
    try {
      const value = await client.post<Study>(path, body, { idempotencyKey: requestKey });
      setStudy(value); setRequestKey(newIdempotencyKey()); await studies.refetch();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function refresh(id = study?.study_id) {
    if (!id) return;
    try { setStudy(await client.get<Study>(`/labor-studies/${id}`, { query: { dataset_id: dataset.dataset_id } })); setError(null); }
    catch (e) { setError(e); }
  }
  async function begin() {
    if (!study) return;
    const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(inputText));
    const input_hash = Array.from(new Uint8Array(hash), n => n.toString(16).padStart(2, '0')).join('');
    await command(`/labor-studies/${study.study_id}/measurements`, { dataset_id: dataset.dataset_id,
      expected_version: study.version, pair_id: pair, task_id: task, task_input_ref: inputRef,
      input_hash, operator, method, planned_order: order });
  }
  async function exportPairs() {
    if (!study) return;
    setBusy(true); setError(null);
    try { onExport(await client.get<Export>(`/labor-studies/${study.study_id}/export`, { query: { dataset_id: dataset.dataset_id } })); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <Panel title="Парные трудозамеры" subtitle="Прошедшее время записывает приложение; активное время отдельно подтверждает человек.">
    <div className="stack">
      <p>Нужны не менее десяти разных пар. Для каждой используйте одинаковый текст и входы, одного оператора и одинаковые границы операции. Время ожидания ответа клиентом не считается трудом. Отрицательная экономия сохраняется.</p>
      {!writable && <p role="status">Для записи измерений выберите рабочую копию набора.</p>}
      <label>Открыть протокол измерений <select value={study?.study_id ?? ''} onChange={e => refresh(e.target.value)}>
        <option value="">Выберите протокол</option>{studies.data?.map(s => <option key={s.study_id} value={s.study_id}>{s.name} · готовых пар {s.ready_pair_count}</option>)}
      </select></label>
      {writable && <details><summary>Новый протокол</summary><div className="stack">
        <label>Название протокола <input value={name} onChange={e => setName(e.target.value)} /></label>
        <label>Наблюдатель <input value={observer} onChange={e => setObserver(e.target.value)} placeholder="Код наблюдателя" /></label>
        <label>Порядок и правила измерения <textarea value={protocol} onChange={e => setProtocol(e.target.value)} /></label>
        <label>Что считается началом <input value={start} onChange={e => setStart(e.target.value)} /></label>
        <label>Что считается завершением <input value={end} onChange={e => setEnd(e.target.value)} /></label>
        <Button disabled={!observer.trim() || !name.trim()} busy={busy} onClick={() => command('/labor-studies', {
          dataset_id: dataset.dataset_id, name, observer, protocol, start_definition: start, end_definition: end,
        })}>Создать протокол</Button>
      </div></details>}
      {study && <>
        <p><strong>{study.name}</strong> · версия {study.version} · готовых пар {study.ready_pair_count}/10</p>
        <p className="small">{study.start_definition} → {study.end_definition}</p>
        <Button onClick={() => refresh()} busy={busy}>Обновить измерения</Button>
        {writable && <details><summary>Начать ручное или автоматизированное выполнение</summary><div className="stack">
          <label>Оператор <input value={operator} onChange={e => setOperator(e.target.value)} placeholder="Код оператора" /></label>
          <div className="row wrap"><label>Идентификатор пары <input value={pair} onChange={e => setPair(e.target.value)} /></label>
            <label>Идентификатор задачи <input value={task} onChange={e => setTask(e.target.value)} /></label></div>
          <label>Ссылка на входные данные задачи <input value={inputRef} onChange={e => setInputRef(e.target.value)} placeholder="Сохранённый запрос, документ или расчёт" /></label>
          <label>Одинаковый текст и параметры задачи <textarea value={inputText} onChange={e => setInputText(e.target.value)} /></label>
          <p className="small">Для обоих способов оставьте этот текст без изменений: приложение проверяет его хеш. Чередуйте порядок способов между парами.</p>
          <div className="row wrap"><label>Способ <select value={method} onChange={e => setMethod(e.target.value as typeof method)}><option value="manual">Вручную</option><option value="app">В GlassFlow</option></select></label>
            <label>Порядок в этой паре <select value={order} onChange={e => setOrder(e.target.value as typeof order)}><option value="manual_first">Сначала вручную</option><option value="app_first">Сначала в GlassFlow</option></select></label></div>
          <Button variant="primary" disabled={!operator.trim() || !pair.trim() || !task.trim() || !inputRef.trim() || !inputText.trim()} busy={busy} onClick={begin}>Начать измерение</Button>
        </div></details>}
        {study.measurements.map(m => <MeasurementRow key={m.measurement_id} value={m} busy={busy} writable={writable} operator={operator}
          action={(operation, fields) => command(`/labor-studies/${study.study_id}/measurements/${m.measurement_id}/${operation}`, {
            dataset_id: dataset.dataset_id, expected_version: study.version, operator: operator || m.operator, ...fields,
          })} />)}
        {study.pairs.length > 0 && <ul>{study.pairs.map(p => <li key={p.pair_id}>{p.task_id} · {p.pair_id}: {p.ready ? `экономия активного времени ${p.saved_active_seconds} с` : PAIR_REASON[p.reason_code ?? ''] ?? 'Проверьте состав и подтверждения пары'}</li>)}</ul>}
        <Button variant="primary" busy={busy} disabled={!study.export_ready} onClick={exportPairs}>Перенести подтверждённые пары в экономику</Button>
        <p className="small muted">Подтверждение оператора сохраняется в истории. Независимую достоверность человеческих показаний приложение не устанавливает.</p>
      </>}
      {(error ?? studies.error) != null && <ErrorState error={error ?? studies.error} />}
    </div>
  </Panel>;
}

function MeasurementRow({ value: m, busy, writable, operator, action }: { value: Measurement; busy: boolean; writable: boolean; operator: string;
  action: (operation: string, fields: Record<string, unknown>) => Promise<void> }) {
  const [resultRef, setResultRef] = useState('');
  const [errors, setErrors] = useState('0');
  const [rework, setRework] = useState('0');
  const [active, setActive] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const fields = { note, acknowledge_interruption: acknowledged };
  return <section className="stack" aria-label={`Измерение ${m.pair_id} ${METHOD[m.method]}`}>
    <h3>{m.task_id} · {m.pair_id} · {METHOD[m.method]}</h3>
    <p>{STATE[m.state]} · прошло {m.elapsed_seconds} с · интервалы работы {m.recorded_running_seconds} с · активное время: {m.attested_active_seconds == null ? 'человек ещё не подтвердил' : `${m.attested_active_seconds} с`}</p>
    {m.interruption_detected && !m.interruption_acknowledged && <label><input type="checkbox" checked={acknowledged} onChange={e => setAcknowledged(e.target.checked)} /> Я проверил незавершённый интервал после перезапуска</label>}
    {writable && m.state !== 'attested' && <>
      <label>Заметка к измерению {m.pair_id} {METHOD[m.method]} <input value={note} onChange={e => setNote(e.target.value)} /></label>
      {m.state === 'running' && <Button busy={busy} onClick={() => action('pause', fields)}>Пауза</Button>}
      {m.state === 'paused' && <Button busy={busy} onClick={() => action('resume', fields)}>Продолжить измерение</Button>}
      {m.state !== 'finished' && <>
        <label>Ссылка на результат {m.pair_id} {METHOD[m.method]} <input value={resultRef} onChange={e => setResultRef(e.target.value)} /></label>
        <div className="row wrap"><label>Ошибки {m.pair_id} {METHOD[m.method]} <input type="number" min="0" value={errors} onChange={e => setErrors(e.target.value)} /></label>
          <label>Переделки, с {m.pair_id} {METHOD[m.method]} <input type="number" min="0" value={rework} onChange={e => setRework(e.target.value)} /></label></div>
        <Button busy={busy} disabled={!resultRef.trim()} onClick={() => action('finish', { ...fields, result_ref: resultRef, error_count: Number(errors), rework_seconds: rework })}>Завершить выполнение</Button>
      </>}
      {m.state === 'finished' && <>
        <label>Подтверждённое активное время, с {m.pair_id} {METHOD[m.method]} <input type="number" min="0" step="0.001" value={active} onChange={e => setActive(e.target.value)} /></label>
        <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> Я, {operator || m.operator}, проверил активное время, ошибки и переделки</label>
        <Button busy={busy} disabled={!confirmed || !active} onClick={() => action('attest', { ...fields, active_seconds: active, human_confirmed: true })}>Подтвердить активное время</Button>
      </>}
    </>}
  </section>;
}

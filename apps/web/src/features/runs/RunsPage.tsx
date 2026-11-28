import { useMutation, useQuery } from '@tanstack/react-query';
import { Download, FileCheck2, Play, ShieldAlert } from 'lucide-react';
import { useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import type { Dataset, ExportResult, Job, RunModule, RunView } from '../../api/types';
import { formatInt, shortHash } from '../../lib/format';
import { href } from '../../state/router';
import { useAppStore } from '../../state/store';
import { Button, ConfirmDialog, Details, EmptyState, ErrorState, LoadingState, Panel, StatusBadge, TableWrap, type Tone } from '../../ui/kit';
import { MODE_LABEL } from '../shell/dataset';
import { JobPanel } from '../shell/JobPanel';
import { RequireDataset } from '../shell/RequireDataset';
import { TERMINAL, useJob } from '../shell/useJob';
import { PassportPanel } from './PassportPanel';

export function RunsPage() {
  return <RequireDataset>{dataset => <Runs dataset={dataset} key={dataset.dataset_id} />}</RequireDataset>;
}

const REQUIRED_INPUTS: { kind: string; label: string; origin: 'new' | 'original' }[] = [
  { kind: 'stock', label: 'Остатки (stock)', origin: 'new' },
  { kind: 'orders', label: 'Детали заказов (orders)', origin: 'new' },
  { kind: 'questions', label: 'Вопросы (questions)', origin: 'new' },
  { kind: 'applications', label: 'Заявки CRM (applications)', origin: 'new' },
  { kind: 'dialogs', label: 'Диалоги (dialogs)', origin: 'new' },
  { kind: 'materials', label: 'materials.csv', origin: 'original' },
  { kind: 'kb', label: 'База знаний (KB JSON)', origin: 'original' },
];

const MODULES: { id: RunModule; label: string; output: string; keyless: string }[] = [
  { id: 'cutting', label: 'Раскрой', output: 'solution.csv', keyless: 'coverage, invalid, missing считаются локально' },
  { id: 'assistant', label: 'Ассистент', output: 'answers.csv', keyless: 'официальной точности нет без KEY' },
  { id: 'crm', label: 'Отбор CRM', output: 'picks.csv', keyless: 'Precision@25 неизвестен без меток' },
  { id: 'quality', label: 'Контроль диалогов', output: 'verdicts.csv', keyless: 'официальной точности нет без KEY' },
  { id: 'cards', label: 'Карточки остатков', output: 'sale_cards.csv', keyless: 'зависят от финального раскроя и реестра' },
];

const RUN_STATUS: Record<RunView['status'], { label: string; tone: Tone }> = {
  running: { label: 'Выполняется', tone: 'pending' },
  completed: { label: 'Все запрошенные модули завершены', tone: 'ok' },
  partial: { label: 'Частично готово: часть модулей не завершена', tone: 'warn' },
  blocked: { label: 'Заблокировано: ни один модуль не завершен', tone: 'error' },
};

const MODULE_STATE: Record<string, { label: string; tone: Tone }> = {
  not_started: { label: 'Не запускался', tone: 'neutral' },
  queued: { label: 'В очереди', tone: 'pending' },
  running: { label: 'Выполняется', tone: 'pending' },
  completed: { label: 'Готово', tone: 'ok' },
  failed: { label: 'Ошибка', tone: 'error' },
  cancelled: { label: 'Остановлено', tone: 'warn' },
  interrupted: { label: 'Прервано', tone: 'warn' },
  blocked: { label: 'Заблокировано', tone: 'error' },
};

function Runs({ dataset }: { dataset: Dataset }) {
  const { api } = useApi();
  const lastRun = useAppStore(state => state.lastRunIds[dataset.dataset_id]);
  const setLastRun = useAppStore(state => state.setLastRun);
  const [modules, setModules] = useState<RunModule[]>(MODULES.map(module => module.id));
  const [jobId, setJobId] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [budget, setBudget] = useState(180);
  const [exportReserve, setExportReserve] = useState(30);
  const [runKey, setRunKey] = useState(newIdempotencyKey);
  const [aiProfile, setAiProfile] = useState<'direct' | 'judge_gateway' | 'local_limited'>('local_limited');
  const present = new Set(Object.keys(dataset.source_hashes));
  const missingInputs = REQUIRED_INPUTS.filter(input => !present.has(input.kind));

  const start = useMutation({
    mutationFn: () =>
      api.createRun(
        { dataset_id: dataset.dataset_id, modules, config_version: 'contest-v1', solver_config: { profile: 'extended', seed: 42, time_limit_seconds: 600, workers: 1, minimum_free_remnants: 5 }, ai_profile: aiProfile, total_budget_seconds: budget, export_reserve_seconds: exportReserve },
        runKey,
      ),
    onSuccess: job => {
      setJobId(job.job_id);
      if (job.run_id) setLastRun(dataset.dataset_id, job.run_id);
      setConfirm(false);
      setRunKey(newIdempotencyKey());
    },
  });
  const job = useJob(jobId);
  const runId = job.data?.run_id ?? (start.data?.run_id || null) ?? lastRun ?? null;
  const run = useQuery({
    queryKey: ['run', runId],
    enabled: Boolean(runId),
    queryFn: ({ signal }) => api.getRun(runId as string, signal),
    refetchInterval: query => (query.state.data && query.state.data.status !== 'running' ? false : 2_000),
  });

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Прогоны</p>
          <h1>Конкурсный запуск: пять входов → проверка → пять файлов</h1>
          <p className="lead">Один неизменный снимок, независимые модули, собственная проверка и официальный validator. Неизвестные результаты не изображаются готовыми.</p>
        </div>
      </header>

      <ol className="flow" aria-label="Этапы прогона">
        <li className={missingInputs.length ? 'warn' : 'done'}>1. Входы</li>
        <li className={jobId || runId ? 'done' : ''}>2. Запуск модулей</li>
        <li className={run.data ? 'done' : ''}>3. Готовность и проверка</li>
        <li className={run.data?.status === 'completed' || run.data?.status === 'partial' ? 'current' : ''}>4. Скачивание</li>
      </ol>

      <Panel title="1. Входные данные" subtitle={`Набор: ${dataset.name} · ${MODE_LABEL[dataset.mode]}`}>
        {dataset.mode !== 'contest' && (
          <div className="state state-warn">
            <ShieldAlert size={18} aria-hidden="true" />
            <div>
              <strong>Выбран не конкурсный снимок</strong>
              <p>
                Конкурсный прогон создается из неизменного снимка: импортируйте пять новых CSV в режиме «Конкурсный снимок».{' '}
                <a href={href('settings', 'data')}>Перейти к импорту</a>
              </p>
            </div>
          </div>
        )}
        <TableWrap label="Входные файлы прогона">
          <table className="table compact">
            <thead>
              <tr>
                <th scope="col">Вход</th>
                <th scope="col">Происхождение</th>
                <th scope="col">Строк</th>
                <th scope="col">SHA-256</th>
                <th scope="col">Состояние</th>
              </tr>
            </thead>
            <tbody>
              {REQUIRED_INPUTS.map(input => (
                <tr key={input.kind}>
                  <td>{input.label}</td>
                  <td>{input.origin === 'new' ? 'новый вход' : 'исходный файл организаторов'}</td>
                  <td className="num">{dataset.row_counts[input.kind] !== undefined ? formatInt(dataset.row_counts[input.kind]) : '—'}</td>
                  <td className="mono small">{shortHash(dataset.source_hashes[input.kind], 16)}</td>
                  <td>{present.has(input.kind) ? <StatusBadge tone="ok">есть</StatusBadge> : <StatusBadge tone="error">отсутствует</StatusBadge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </Panel>

      <Panel title="2. Модули" subtitle="Модули выполняются независимо: сбой одного не стирает готовые результаты других.">
        <fieldset className="fieldset">
          <legend>Что запустить</legend>
          <div className="module-grid">
            {MODULES.map(module => (
              <label key={module.id} className="check module-option">
                <input
                  type="checkbox"
                  checked={modules.includes(module.id)}
                  onChange={event => setModules(current => (event.target.checked ? [...current, module.id] : current.filter(item => item !== module.id)))}
                />
                <span>
                  <b>{module.label}</b> → <span className="mono">{module.output}</span>
                  <small>{module.keyless}</small>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <label className="inline-field">
          AI-профиль прогона
          <select value={aiProfile} onChange={event => setAiProfile(event.target.value as typeof aiProfile)}>
            <option value="direct">Прямой проверенный ключ команды</option>
            <option value="judge_gateway">Шлюз judge_gateway</option>
            <option value="local_limited">Только локальный режим (ассистент может быть неполным)</option>
          </select>
        </label>
        <div className="form-row"><label>Общий бюджет, секунд<input type="number" min={60} max={7200} value={budget} onChange={e => setBudget(Number(e.target.value))} /></label><label>Резерв на проверку и экспорт, секунд<input type="number" min={10} max={budget - 1} value={exportReserve} onChange={e => setExportReserve(Number(e.target.value))} /></label></div>
        <p className="small muted">Сначала сохраняется полный допустимый комплект, затем оставшееся время используется для улучшений.</p>
        <div className="row">
          <Button variant="primary" icon={<Play size={14} aria-hidden="true" />} disabled={!modules.length || missingInputs.length > 0} onClick={() => setConfirm(true)}>
            Запустить прогон
          </Button>
          {missingInputs.length > 0 && <small className="text-warn">Не хватает входов: {missingInputs.map(input => input.kind).join(', ')}</small>}
        </div>
        {jobId && <JobPanel jobId={jobId} title="Задание прогона" />}
      </Panel>

      <Panel title="3. Готовность и проверка" subtitle={runId ? `run_id ${runId}` : undefined}>
        {!runId && <EmptyState title="Прогон еще не запускался" />}
        {runId && run.isLoading && <LoadingState label="Получаем состояние прогона…" />}
        {run.isError && <ErrorState error={run.error} onRetry={() => run.refetch()} context="Прогон" />}
        {run.data && <RunStatus run={run.data} />}
        {run.data?.budget && <p className="small">Бюджет прогона: {JSON.stringify(run.data.budget)}</p>}
        {runId && <PassportPanel datasetId={dataset.dataset_id} runId={runId} />}
      </Panel>

      {run.data && runId && (TERMINAL.includes(job.data?.state ?? 'completed') || !jobId) && <ExportPanel run={run.data} runId={runId} />}

      <ConfirmDialog
        open={confirm}
        onOpenChange={value => {
          setConfirm(value);
          if (!value) start.reset();
        }}
        title="Запустить конкурсный прогон"
        action="Будет создан неизменный run из выбранного снимка с фиксированной конфигурацией. Изменения рабочих копий в прогон не попадают."
        affected={[
          { label: 'Набор', value: `${dataset.name} (${MODE_LABEL[dataset.mode]})` },
          { label: 'Модули', value: modules.map(id => MODULES.find(module => module.id === id)?.label).join(', ') },
          { label: 'Конфигурация', value: 'contest-v1 · раскрой extended 600 с, seed 42, 1 поток' },
          { label: 'AI-профиль', value: aiProfile },
        ]}
        confirmLabel="Запустить"
        onConfirm={() => start.mutate()}
        busy={start.isPending}
        error={start.error}
      />
    </div>
  );
}

function RunStatus({ run }: { run: RunView }) {
  const status = RUN_STATUS[run.status];
  const requested = (run.manifest.modules as RunModule[] | undefined) ?? MODULES.map(module => module.id);
  const jobOf = (module: RunModule): Job | undefined => run.jobs.find(job => job.kind === module);
  /** Pro's Job DTO has no `kind` yet (requested): fall back to missing_modules, which the run view reports authoritatively. */
  const stateOf = (module: RunModule): string => {
    const job = jobOf(module);
    if (job) return job.state;
    if (!run.missing_modules.includes(module)) return 'completed';
    return run.status === 'running' ? 'running' : 'failed';
  };
  return (
    <div className="stack">
      <div className="row wrap">
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
        <StatusBadge tone="neutral">Официальные баллы ассистента, CRM и диалогов неизвестны без KEY</StatusBadge>
      </div>
      {run.missing_modules.length > 0 && run.status !== 'running' && (
        <p className="small text-warn">Не завершены: {run.missing_modules.join(', ')}. Готовые части доступны с частичным статусом; чужие ответы не подставляются.</p>
      )}
      <TableWrap label="Модули прогона">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Модуль</th>
              <th scope="col">Состояние</th>
              <th scope="col">Этап</th>
              <th scope="col">Файл</th>
              <th scope="col">Проверка без KEY</th>
              <th scope="col">Ошибка</th>
            </tr>
          </thead>
          <tbody>
            {MODULES.filter(module => requested.includes(module.id)).map(module => {
              const job = jobOf(module.id);
              const state = MODULE_STATE[stateOf(module.id)] ?? MODULE_STATE.not_started;
              return (
                <tr key={module.id}>
                  <td>{module.label}</td>
                  <td>
                    <StatusBadge tone={state.tone}>{state.label}</StatusBadge>
                  </td>
                  <td className="small">{job?.stage ?? '—'}</td>
                  <td className="mono">{module.output}</td>
                  <td className="small">{module.keyless}</td>
                  <td className="small">{job?.error_code ?? '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableWrap>
      <Details summary="Паспорт воспроизводимости (RunManifest)">
        <pre className="pre small">{JSON.stringify(run.manifest, null, 2)}</pre>
      </Details>
    </div>
  );
}

function ExportPanel({ run, runId }: { run: RunView; runId: string }) {
  const { api } = useApi();
  const [key, setKey] = useState(newIdempotencyKey);
  const [open, setOpen] = useState(false);
  const exportRun = useMutation({
    mutationFn: () => api.exportRun(runId, key),
    onSuccess: () => {
      setOpen(false);
      setKey(newIdempotencyKey());
    },
  });
  const result: ExportResult | undefined = exportRun.data;
  const downloadable = (value: string) => /^(\/|https?:|blob:)/.test(value);
  return (
    <Panel title="4. Скачать результаты" subtitle="Все файлы относятся к одному run. buyers_top50.csv лежит в корне сдачи, не в closed_run.">
      <div className="row">
        <Button variant="primary" icon={<FileCheck2 size={14} aria-hidden="true" />} onClick={() => setOpen(true)} disabled={run.status === 'running'}>
          Проверить и подготовить файлы
        </Button>
      </div>
      {exportRun.error && <ErrorState error={exportRun.error} onRetry={() => exportRun.mutate()} context="Экспорт" />}
      {result && (
        <div className="stack">
          <StatusBadge tone={result.status === 'ready' ? 'ok' : result.status === 'partial' ? 'warn' : 'error'}>
            {result.status === 'ready' ? 'Пакет готов: выходы одного run прошли проверки' : result.status === 'partial' ? 'Частичный пакет — не выдавайте за полный' : 'Экспорт заблокирован'}
          </StatusBadge>
          {result.errors.length > 0 && (
            <ul className="plain small text-error">
              {result.errors.map((error, index) => (
                <li key={index}>{error}</li>
              ))}
            </ul>
          )}
          <ul className="downloads">
            {Object.entries(result.files).map(([name, target]) => (
              <li key={name}>
                <span className="mono">{name}</span>
                {downloadable(target) ? (
                  <a className="btn btn-secondary" href={target.startsWith('/') && !target.startsWith('/api/') ? `/api/v1${target}` : target} download={name}>
                    <Download size={14} aria-hidden="true" /> <span>Скачать</span>
                  </a>
                ) : (
                  <span className="small muted">{target}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <ConfirmDialog
        open={open}
        onOpenChange={value => {
          setOpen(value);
          if (!value) exportRun.reset();
        }}
        title="Подготовить файлы прогона"
        action="Сервер запишет файлы во временные пути, перечитает их, проверит заголовки/ID/числа, запустит официальные validate.py и selfcheck.py и только затем заменит готовые артефакты."
        affected={[
          { label: 'run_id', value: <span className="mono">{runId}</span> },
          { label: 'Статус прогона', value: RUN_STATUS[run.status].label },
        ]}
        confirmLabel="Проверить и подготовить"
        onConfirm={() => exportRun.mutate()}
        busy={exportRun.isPending}
        error={exportRun.error}
      />
    </Panel>
  );
}

/**
 * TEST-ONLY fixture transport. Selected exclusively by VITE_GLASSFLOW_TRANSPORT=fixture
 * (pnpm dev:fixture / fixture E2E) or explicitly in unit tests. Responses are canned
 * scenario answers, not product logic: unknown requests return a clear 501/needs_review
 * instead of inventing results. A purple banner marks every screen in this mode.
 *
 * window.__glassflowFixture exposes scenario controls for browser tests:
 *   failNext(pathPrefix, status, code?) — next matching request fails with the envelope;
 *   setAiOffline(true|false)            — assistant replies in local_limited mode;
 *   bumpRemnant(id)                     — simulate a concurrent change → 409 on confirm;
 *   takeRemnant(id)                     — another user reserved the remnant (status + version);
 *   setOffline(true|false)              — every request fails at network level;
 *   reset()
 */
import type {
  AISettings,
  AssistantReply,
  BackupInfo,
  Candidate,
  CutPlan,
  Dataset,
  DialogVerdict,
  ImportPreview,
  Job,
  ManagerMetrics,
  MetricEvidence,
  RunView,
  Quote,
  Reminder,
  Remnant,
  SaleCard,
} from '../types';
import { TransportFailure, type Transport, type TransportRequest, type TransportResponse } from '../transport';
import * as data from './data';

interface State {
  datasets: Dataset[];
  remnants: Record<string, Remnant[]>;
  plans: Record<string, CutPlan[]>;
  quotes: Record<string, Quote>;
  reminders: Record<string, Reminder[]>;
  cards: Record<string, SaleCard[]>;
  jobs: Record<string, Job & { polls: number; kind: string; target?: number }>;
  runs: Record<string, RunView & { run_id: string; dataset_id: string }>;
  settings: AISettings;
  backups: BackupInfo[];
  imports: Record<string, ImportPreview>;
  failures: { prefix: string; status: number; code: string }[];
  aiOffline: boolean;
  offline: boolean;
  bumped: Set<string>;
  counter: number;
  idempotency: Map<string, { hash: string; response: TransportResponse }>;
}

const applications = data.makeApplications();

function initial(): State {
  const datasets = data.makeDatasets();
  const remnants: Record<string, Remnant[]> = {};
  const plans: Record<string, CutPlan[]> = {};
  for (const dataset of datasets) {
    remnants[dataset.dataset_id] = data.makeRemnants(dataset.dataset_id);
    const plan = data.makePlan(dataset.dataset_id);
    plans[dataset.dataset_id] = [plan];
    const used = new Set(plan.placements.filter(item => item.remnant_id !== 'NEW').map(item => item.remnant_id));
    if (dataset.mode === 'workspace') for (const r of remnants[dataset.dataset_id]) if (used.has(r.remnant_id)) r.status = 'reserved';
  }
  return {
    datasets,
    remnants,
    plans,
    quotes: {},
    reminders: {},
    cards: {},
    jobs: {},
    runs: {},
    settings: {
      version: 0,
      profile: 'local_limited',
      provider: 'gemini',
      model_id: '',
      mode: 'free_only',
      paid_enabled: false,
      monthly_budget_tg: '0',
      rpm: 10,
      max_parallel: 1,
      timeout_seconds: 30,
      max_retries: 2,
      gateway_url: null,
      secret_present: false,
      allowed_models: ['gemini-3.8-flash', 'gemini-4-hydrogen'],
    },
    backups: [{ backup_id: 'backup-fixture-1', created_at: '2026-11-27T06:00:00Z', size_bytes: 524288, integrity: 'ok' }],
    imports: {},
    failures: [],
    aiOffline: false,
    offline: false,
    bumped: new Set(),
    counter: 1,
    idempotency: new Map(),
  };
}

const ok = (body: unknown, status = 200): TransportResponse => ({ status, headers: { 'content-type': 'application/json', 'x-correlation-id': `fx-${Math.random().toString(36).slice(2, 10)}` }, body });
const fail = (status: number, code: string, message_ru: string, extra: Partial<{ field_errors: Record<string, string>[]; conflict_objects: string[]; retryable: boolean }> = {}): TransportResponse =>
  ok({ code, message_ru, field_errors: extra.field_errors ?? [], conflict_objects: extra.conflict_objects ?? [], retryable: extra.retryable ?? false, correlation_id: `fx-${Math.random().toString(36).slice(2, 10)}` }, status);

type Body = Record<string, unknown>;

export function createFixtureTransport(): Transport {
  let state = initial();
  const nextId = (prefix: string) => `${prefix}-${state.counter++}`;
  const datasetOf = (id: unknown) => state.datasets.find(item => item.dataset_id === id);

  const controls = {
    failNext: (prefix: string, status: number, code = `FIXTURE_${status}`) => state.failures.push({ prefix, status, code }),
    setAiOffline: (value: boolean) => (state.aiOffline = value),
    setOffline: (value: boolean) => (state.offline = value),
    bumpRemnant: (id: string) => {
      state.bumped.add(id);
      for (const list of Object.values(state.remnants)) for (const r of list) if (r.remnant_id === id) r.version = (r.version ?? 0) + 1;
    },
    takeRemnant: (id: string) => {
      for (const list of Object.values(state.remnants))
        for (const r of list)
          if (r.remnant_id === id) {
            r.status = 'reserved';
            r.version = (r.version ?? 0) + 1;
          }
    },
    reset: () => (state = initial()),
  };
  if (typeof window !== 'undefined') (window as unknown as { __glassflowFixture: typeof controls }).__glassflowFixture = controls;

  function route(req: TransportRequest): TransportResponse {
    const { method, path } = req;
    const q = req.query ?? {};
    const body = (req.body ?? {}) as Body;
    const datasetId = (q.dataset_id ?? body.dataset_id) as string | undefined;
    const seg = path.split('/').filter(Boolean);

    // ---------- platform ----------
    if (path === '/health') return ok({ status: 'ok', app: 'GlassFlow', version: '0.1.0-fixture' });
    if (path === '/ready')
      return ok({ status: 'degraded', database: true, business_modules_ready: false, schema: true, worker: true, ai: state.aiOffline ? 'unavailable' : 'unchecked', modules: { platform: true, cutting: false, intelligence: true, crm: true, sales: true } });
    if (path === '/session') return ok({ session_token: 'fixture-session-token' });
    if (path === '/datasets' && method === 'GET') return ok(state.datasets);
    if (seg[0] === 'datasets' && seg.length === 2) {
      const dataset = datasetOf(seg[1]);
      return dataset ? ok(dataset) : fail(404, 'DATASET_NOT_FOUND', 'Набор не найден.');
    }
    if (seg[0] === 'datasets' && seg[2] === 'working-copy' && method === 'POST') {
      const source = datasetOf(seg[1]);
      if (!source) return fail(404, 'DATASET_NOT_FOUND', 'Набор не найден.');
      const copy: Dataset = { ...source, dataset_id: nextId('ds-copy'), name: String(body.name ?? 'Рабочая копия'), mode: 'workspace', parent_id: source.dataset_id, created_at: new Date().toISOString() };
      state.datasets.push(copy);
      state.remnants[copy.dataset_id] = data.makeRemnants(copy.dataset_id);
      state.plans[copy.dataset_id] = [data.makePlan(copy.dataset_id)];
      return ok(copy);
    }
    if (path === '/imports/preview' && method === 'POST') {
      const names = req.form ? (req.form.getAll('files') as File[]).map(file => file.name) : [];
      const bad = names.some(name => /bad|ошиб/i.test(name));
      const preview: ImportPreview = {
        import_id: nextId('imp'),
        row_counts: { materials: 6, stock: 16, orders: 12, questions: 18, dialogs: 8, applications: 60 },
        errors: bad
          ? [
              { file: 'stock_bad.csv', row: '4', field: 'длина_мм', raw: '-120', reason: 'Размер должен быть положительным целым' },
              { file: 'stock_bad.csv', row: '9', field: 'material_id', raw: 'clear-5', reason: 'Неизвестный material_id: строка не будет использоваться в раскрое' },
              { file: 'orders_bad.csv', row: '3', field: 'part_id', raw: 'P0002', reason: 'Повтор ID' },
            ]
          : [],
        warnings: ['questions_open_KEY.csv: evaluation/служебный файл исключен из runtime'],
      };
      state.imports[preview.import_id] = preview;
      return ok(preview);
    }
    if (seg[0] === 'imports' && seg[2] === 'commit') {
      const preview = state.imports[seg[1]];
      if (!preview) return fail(404, 'IMPORT_NOT_FOUND', 'Предпросмотр не найден.');
      if (preview.errors.length) return fail(422, 'IMPORT_INVALID', 'Исправьте все ошибки импорта.', { field_errors: preview.errors });
      if (!body.explicit_copy) {
        const same = state.datasets.find(item => item.mode === body.mode);
        if (same) return ok(same);
      }
      const created: Dataset = { ...data.makeDatasets()[0], dataset_id: nextId('ds'), name: String(body.name), mode: body.mode as Dataset['mode'], created_at: new Date().toISOString() };
      state.datasets.push(created);
      state.remnants[created.dataset_id] = data.makeRemnants(created.dataset_id);
      state.plans[created.dataset_id] = [data.makePlan(created.dataset_id)];
      return ok(created);
    }

    // ---------- jobs & runs ----------
    if (seg[0] === 'jobs' && seg.length === 2) {
      const job = state.jobs[seg[1]];
      if (!job) return fail(404, 'JOB_NOT_FOUND', 'Задание не найдено.');
      job.polls += 1;
      advanceJob(job);
      const { polls: _polls, target: _target, ...visible } = job;
      void _polls;
      void _target;
      return ok(visible);
    }
    if (seg[0] === 'jobs' && seg[2] === 'cancel') {
      const job = state.jobs[seg[1]];
      if (!job) return fail(404, 'JOB_NOT_FOUND', 'Задание не найдено.');
      if (job.state === 'queued' || job.state === 'running') job.cancel_requested = true;
      return ok(job);
    }
    if (path === '/runs' && method === 'POST') {
      const dataset = datasetOf(body.dataset_id);
      if (!dataset) return fail(404, 'DATASET_NOT_FOUND', 'Набор не найден.');
      const runId = nextId('run');
      const modules = ((body.modules as string[]) ?? []) as RunView['missing_modules'];
      const jobs = modules.map(module => {
        const job = createJob(module, { run_id: runId, dataset_id: dataset.dataset_id });
        return job;
      });
      state.runs[runId] = {
        run_id: runId,
        dataset_id: dataset.dataset_id,
        manifest: { run_id: runId, dataset_id: dataset.dataset_id, modules, config_version: String(body.config_version), note: 'FIXTURE — не настоящий RunManifest' },
        status: 'running',
        jobs,
        missing_modules: modules,
      };
      return ok(createJob('run', { run_id: runId, dataset_id: dataset.dataset_id }), 202);
    }
    if (seg[0] === 'runs' && seg.length === 2) {
      const run = state.runs[seg[1]];
      if (!run) return fail(404, 'RUN_NOT_FOUND', 'Прогон не найден.');
      // Advance one module per poll so the UI shows real intermediate states.
      const next = run.jobs.find(job => job.state === 'queued' || job.state === 'running');
      if (next) {
        const failed = (next.kind === 'assistant' && state.aiOffline) || (next.kind === 'cards' && run.jobs.find(job => job.kind === 'cutting')?.state === 'failed');
        next.state = failed ? 'failed' : 'completed';
        next.stage = failed ? 'Ошибка модуля' : 'Готово';
        next.error_code = failed ? (next.kind === 'assistant' ? 'AI_UNAVAILABLE' : 'CUTTING_NOT_COMPLETED') : null;
      }
      const done = run.jobs.filter(job => job.state === 'completed').map(job => job.kind as RunView['missing_modules'][number]);
      const waiting = run.jobs.some(job => job.state === 'queued' || job.state === 'running');
      run.status = waiting ? 'running' : done.length === run.jobs.length ? 'completed' : done.length ? 'partial' : 'blocked';
      run.missing_modules = (run.manifest.modules ?? []).filter(module => !done.includes(module));
      const { run_id: _r, dataset_id: _d, ...view } = run;
      void _r;
      void _d;
      return ok(view);
    }
    if (seg[0] === 'runs' && seg[2] === 'export') {
      const run = state.runs[seg[1]];
      if (!run) return fail(404, 'RUN_NOT_FOUND', 'Прогон не найден.');
      const headers: Record<string, [string, string]> = {
        cutting: ['solution.csv', 'part_id,remnant_id,x_mm,y_mm,rot'],
        assistant: ['answers.csv', 'id,answer'],
        crm: ['picks.csv', 'app_id'],
        quality: ['verdicts.csv', 'id,verdict,correct'],
        cards: ['sale_cards.csv', 'remnant_id,title,price_tg,description,target_buyer,top3_buyers'],
      };
      const files: Record<string, string> = {};
      for (const job of run.jobs.filter(item => item.state === 'completed')) {
        const [name, header] = headers[job.kind as string];
        files[name] = URL.createObjectURL(new Blob([`${header}\n`], { type: 'text/csv' }));
      }
      const missing = run.jobs.filter(item => item.state !== 'completed');
      return ok({ run_id: run.run_id, status: missing.length === 0 && run.jobs.length === 5 ? 'ready' : Object.keys(files).length ? 'partial' : 'blocked', files, errors: missing.map(job => `${job.kind}: ${job.error_code ?? job.state}`) });
    }

    // ---------- settings & system ----------
    if (path === '/settings' && method === 'GET') return ok(state.settings);
    if (path === '/settings' && method === 'PATCH') {
      const { api_key, ...rest } = body as Body & { api_key?: string };
      if (rest.mode === 'paid_enabled' && (!rest.monthly_budget_tg || rest.monthly_budget_tg === '0'))
        return fail(422, 'BUDGET_REQUIRED', 'Укажите бюджет платного профиля.', { field_errors: [{ field: 'body.monthly_budget_tg', reason: 'Для платного профиля нужен положительный бюджет' }] });
      state.settings = { ...state.settings, ...(rest as Partial<AISettings>), version: state.settings.version + 1, secret_present: state.settings.secret_present || Boolean(api_key) };
      return ok(state.settings);
    }
    // Mirrors Pro 6512eae: the AI checker is not wired → 503; list/journal routes do not exist yet → HTTP_404.
    if (path === '/settings/ai/check') return fail(503, 'AI_ADAPTER_UNAVAILABLE', 'Проверка AI-провайдера пока не подключена; локальное ядро доступно.', { retryable: true });
    if (path === '/system/backups' || path === '/system/journal') return fail(404, 'HTTP_404', 'Запрос не выполнен.');
    if (path === '/system/backup') {
      const info = { backup_id: nextId('backup'), created_at: new Date().toISOString(), sha256: 'fx'.repeat(32), integrity: 'ok' };
      state.backups.unshift(info);
      return ok(info);
    }
    if (path === '/system/restore') return ok({ restored: true, previous_backup_id: nextId('backup-before-restore') });
    if (path === '/system/shutdown') return ok({ status: 'worker_stopped', restart_required: true });

    // ---------- domain: dataset scope required ----------
    if (!datasetId || !datasetOf(datasetId)) {
      if (['remnants', 'cutting', 'plans', 'catalog', 'quotes', 'assistant', 'quality', 'crm', 'analytics', 'sale-cards'].includes(seg[0]))
        return fail(404, 'DATASET_NOT_FOUND', 'Набор не найден.');
    }
    const dataset = datasetOf(datasetId);
    const mutableOnly = () => (dataset && dataset.mode !== 'workspace' ? fail(409, 'DATASET_IMMUTABLE', 'Исходный и конкурсный снимки не изменяются. Создайте рабочую копию.') : null);

    // ---------- cutting ----------
    if (path === '/remnants' && method === 'GET') return ok(state.remnants[datasetId!]);
    if (path === '/remnants' && method === 'POST') {
      const blocked = mutableOnly();
      if (blocked) return blocked;
      const created: Remnant = {
        dataset_id: datasetId!,
        remnant_id: `R${String(state.remnants[datasetId!].length + 1).padStart(3, '0')}`,
        material_id: String(body.material_id),
        dimensions: body.dimensions as Remnant['dimensions'],
        defect: Boolean(body.defect),
        location_raw: String(body.location_raw),
        age_days: (body.age_days as number | null) ?? null,
        status: 'available',
        version: 0,
      };
      state.remnants[datasetId!].push(created);
      return ok(created);
    }
    if (seg[0] === 'remnants' && seg[2] === 'reserve') {
      const blocked = mutableOnly();
      if (blocked) return blocked;
      const target = state.remnants[datasetId!].find(item => item.remnant_id === seg[1]);
      if (!target) return fail(404, 'REMNANT_NOT_FOUND', 'Остаток не найден в этом наборе.');
      if (body.expected_version !== target.version || target.status !== 'available')
        return fail(409, 'REMNANT_CONFLICT', 'Остаток уже изменен или занят. Показано актуальное состояние.', { conflict_objects: [target.remnant_id] });
      target.status = 'reserved';
      target.version = (target.version ?? 0) + 1;
      return ok(target);
    }
    if (seg[0] === 'remnants' && seg.length === 3) {
      const blocked = mutableOnly();
      if (blocked) return blocked;
      const target = state.remnants[datasetId!].find(item => item.remnant_id === seg[1]);
      if (!target) return fail(404, 'REMNANT_NOT_FOUND', 'Остаток не найден в этом наборе.');
      if (body.expected_version !== target.version) return fail(409, 'VERSION_CONFLICT', 'Версия остатка изменилась.', { conflict_objects: [target.remnant_id] });
      if (seg[2] === 'consume') target.status = 'consumed';
      if (seg[2] === 'release') target.status = 'available';
      if (seg[2] === 'measurement') target.dimensions = body.dimensions as Remnant['dimensions'];
      target.version = (target.version ?? 0) + 1;
      return ok(target);
    }
    if (path === '/cutting/parts') return ok(data.parts);
    if (path === '/cutting/materials') return ok(data.materials);
    if (path === '/plans' && method === 'GET') return ok(state.plans[datasetId!]);
    if (path === '/plans/compare') {
      const list = state.plans[datasetId!];
      const base = list.find(item => item.plan_id === body.base_plan_id);
      const candidate = list.find(item => item.plan_id === body.candidate_plan_id);
      if (!base || !candidate) return fail(404, 'PLAN_NOT_FOUND', 'План не найден.');
      const baseNew = new Set(base.placements.filter(item => item.remnant_id === 'NEW').map(item => item.part_id));
      const candNew = new Set(candidate.placements.filter(item => item.remnant_id === 'NEW').map(item => item.part_id));
      return ok({
        base: { plan_id: base.plan_id, revision: base.revision, metrics: base.metrics },
        candidate: { plan_id: candidate.plan_id, revision: candidate.revision, metrics: candidate.metrics },
        delta_covered_area_mm2: candidate.metrics.covered_area_mm2 - base.metrics.covered_area_mm2,
        delta_replacement_value_tg: '0.00',
        delta_fully_covered_orders: candidate.metrics.fully_covered_orders - base.metrics.fully_covered_orders,
        newly_new_part_ids: [...candNew].filter(id => !baseNew.has(id)),
        newly_placed_part_ids: [...baseNew].filter(id => !candNew.has(id)),
        affected_quote_ids: [],
        affected_sale_card_ids: (state.cards[datasetId!] ?? []).map(card => card.card_id as string),
      });
    }
    if (seg[0] === 'plans' && seg.length === 2) {
      const plan = state.plans[datasetId!]?.find(item => item.plan_id === seg[1]);
      return plan ? ok(plan) : fail(404, 'PLAN_NOT_FOUND', 'План не найден в этом наборе.');
    }
    if (seg[0] === 'plans' && seg[2] === 'draft') {
      const blocked = mutableOnly();
      if (blocked) return blocked;
      const list = state.plans[datasetId!];
      const base = list.find(item => item.plan_id === seg[1]);
      if (!base) return fail(404, 'PLAN_NOT_FOUND', 'План не найден.');
      const draft: CutPlan = { ...base, plan_id: nextId('PLAN-DRAFT'), revision: base.revision + 1, status: 'draft', placements: body.placements as CutPlan['placements'], parent_plan_id: base.plan_id };
      list.push(draft);
      return ok(draft);
    }
    if (seg[0] === 'plans' && seg[2] === 'validate') {
      const plan = state.plans[datasetId!]?.find(item => item.plan_id === seg[1]);
      if (!plan) return fail(404, 'PLAN_NOT_FOUND', 'План не найден.');
      // Fixture validator: flags placements closer than 5 mm to the origin edges only — enough to drive UI states.
      const invalid = plan.placements.filter(item => item.remnant_id !== 'NEW' && item.x_mm !== null && item.y_mm !== null && ((item.x_mm ?? 0) < 5 || (item.y_mm ?? 0) < 5));
      plan.status = invalid.length ? 'invalid' : 'validated';
      return ok({ valid: invalid.length === 0, errors: invalid.map(item => `${item.part_id}: ближе 5 мм к краю (фикстура)`), invalid_part_ids: invalid.map(item => item.part_id), missing_part_ids: [] });
    }
    if (seg[0] === 'plans' && seg[2] === 'commit') {
      const blocked = mutableOnly();
      if (blocked) return blocked;
      const list = state.plans[datasetId!];
      const plan = list.find(item => item.plan_id === seg[1]);
      if (!plan) return fail(404, 'PLAN_NOT_FOUND', 'План не найден.');
      const expected = body.expected_remnant_versions as Record<string, number>;
      const conflicts = Object.entries(expected).filter(([id, version]) => state.remnants[datasetId!].find(item => item.remnant_id === id)?.version !== version).map(([id]) => id);
      if (conflicts.length) return fail(409, 'VERSION_CONFLICT', 'Версии остатков изменились; обновите план.', { conflict_objects: conflicts });
      for (const item of list) if (item.status === 'committed') item.status = 'superseded';
      plan.status = 'committed';
      for (const card of state.cards[datasetId!] ?? []) {
        card.status = 'stale';
        card.stale_reason = `План изменен: ${plan.plan_id} ревизия ${plan.revision}`;
      }
      return ok(plan);
    }
    if (path === '/cutting/solve') return ok(createJob('solve', { dataset_id: datasetId! }));
    if (path === '/cutting/candidates') {
      const dims = body.dimensions as { length_mm: number; width_mm: number };
      if (body.material_id === 'clear-6' && dims.length_mm <= 450 && dims.width_mm <= 370) {
        const r = state.remnants[datasetId!].find(item => item.remnant_id === 'R006')!;
        if (r.status !== 'available') return ok({ candidates: [], reason_codes: ['occupied_by_reservation'], scope: 'free_whole_remnants' });
        const candidate: Candidate = { remnant_id: 'R006', remnant_version: r.version ?? 0, x_mm: 5, y_mm: 5, rot: 0, location_raw: r.location_raw, length_mm: 460, width_mm: 380, material_id: 'clear-6' };
        return ok({ candidates: [candidate], reason_codes: [], scope: 'free_whole_remnants' });
      }
      return ok({ candidates: [], reason_codes: ['no_free_whole_remnant'], scope: 'free_whole_remnants' });
    }

    // ---------- intelligence ----------
    if (path === '/catalog') return ok(data.catalog);
    if (path === '/quotes' && method === 'POST') return ok(cannedQuote(nextId('Q'), 1, body));
    if (seg[0] === 'quotes' && seg.length === 2) {
      const quote = state.quotes[seg[1]];
      return quote ? ok(quote) : fail(404, 'QUOTE_NOT_FOUND', 'Расчет не найден.');
    }
    if (seg[0] === 'quotes' && seg[2] === 'revise') {
      const quote = state.quotes[seg[1]];
      if (!quote) return fail(404, 'QUOTE_NOT_FOUND', 'Расчет не найден.');
      if (body.expected_revision !== quote.revision) return fail(409, 'REVISION_CONFLICT', 'Расчет уже изменен.', { conflict_objects: [quote.quote_id] });
      const changed = body.changes as Body;
      const merged = { catalog_product_id: quote.catalog_product_id, dimensions: quote.dimensions, quantity: quote.quantity, processing: quote.processing, customer_id: quote.customer_id, ...changed, dataset_id: datasetId, inventory_mode: 'free_whole_remnants' };
      const next = cannedQuote(quote.quote_id, quote.revision + 1, merged);
      next.diff = {
        from_revision: quote.revision,
        to_revision: next.revision,
        changed_fields: Object.keys(changed).filter(field => JSON.stringify(changed[field]) !== JSON.stringify((quote as Record<string, unknown>)[field])),
        lines: next.components.map((line, index) => ({ component: line.component ?? line.label, before_tg: quote.components[index]?.amount_tg ?? null, after_tg: line.amount_tg })),
        total_before_tg: quote.total_tg,
        total_after_tg: next.total_tg,
      };
      return ok(next);
    }
    if (seg[0] === 'quotes' && seg[2] === 'confirm') {
      const blocked = mutableOnly();
      if (blocked) return blocked;
      const quote = state.quotes[seg[1]];
      if (!quote) return fail(404, 'QUOTE_NOT_FOUND', 'Расчет не найден.');
      if (body.expected_revision !== quote.revision) return fail(409, 'REVISION_CONFLICT', 'Расчет изменен; подтвердите актуальную ревизию.', { conflict_objects: [quote.quote_id] });
      quote.status = 'confirmed';
      quote.confirmed_by = String(body.confirmed_by);
      quote.confirmed_at = new Date().toISOString();
      return ok(quote);
    }
    if (path === '/assistant/turns') {
      const text = String(body.text);
      const conversation = (body.conversation_id as string) || nextId('conv');
      const dims = /(\d{3,4})\s*[x×х]\s*(\d{3,4})/.exec(text);
      const reply: AssistantReply = {
        conversation_id: conversation,
        answer: dims
          ? `Предварительно рассчитаем стекло ${dims[1]}×${dims[2]} мм. Уточните толщину и обработку кромки, если они отличаются от указанных.`
          : 'Уточните, пожалуйста, материал, толщину и размеры детали в миллиметрах.',
        clarification: /серое/i.test(text) && !/8\s*мм/.test(text) ? 'Какая толщина серого стекла? Цена 10 000 и 20 000 ₸/м² относится к разным позициям.' : null,
        quote: null,
        evidence: [{ source: 'kb', source_version: 'sha256:fixture-kb', record_id: 'steklo-6-prozrachnoe', field: 'цена_за_м2_тг' }],
        mode: state.aiOffline ? 'local_limited' : 'online',
        provider: state.aiOffline ? null : 'fixture',
        model_id: state.aiOffline ? null : 'fixture-model',
        status: dims ? 'answered' : 'clarification',
        answer_path: state.aiOffline ? 'fallback' : 'deterministic',
        ai_unavailable_reason: state.aiOffline ? 'Фикстура: AI-провайдер отключен' : null,
        card: {
          intent: 'quote',
          catalog_product_id: dims ? 'steklo-6-prozrachnoe' : null,
          product_name: dims ? 'Стекло 6 мм прозрачное' : null,
          confirmed_parameters: dims ? { catalog_product_id: 'steklo-6-prozrachnoe', length_mm: dims[1], width_mm: dims[2] } : {},
          assumptions: dims ? ['количество 1 шт — не подтверждено клиентом'] : [],
          missing_parameters: dims ? ['обработка кромки'] : ['материал', 'толщина', 'размеры'],
          normalized_dimensions: dims ? `${dims[1]}×${dims[2]} мм` : null,
          facts: dims ? [{ fact_id: 'f1', kind: 'цена за м²', value: '8000', unit: '₸/м²', source_ref: 'kb:steklo-6-prozrachnoe', status: 'supported' }] : [],
          alternatives: [],
          needs_manager: false,
        },
        tool_calls: [{ tool: 'search_catalog', status: 'ok', summary: 'фикстура' }],
      };
      return ok(reply);
    }
    if (seg[0] === 'assistant' && seg[1] === 'conversations') return fail(404, 'CONVERSATION_NOT_FOUND', 'Диалог не найден.');
    if (path === '/quality/check') {
      const manager = String(body.manager);
      let verdict: DialogVerdict;
      if (/10\s?050/.test(manager)) verdict = { id: String(body.id), verdict: 'ERROR', correct: '10000', evidence: [{ source: 'kb', source_version: 'sha256:fixture-kb', record_id: 'steklo-seroe', field: 'цена_за_м2_тг' }], explanation_ru: 'Фикстура: в ответе 10 050 ₸, в KB 10 000 ₸/м².', reference_tg: '10000', reference_meaning: 'per_m2', mentions: [{ raw: '10 050 тг', amount_tg: '10050', meaning: 'per_m2' }] };
      else if (/10\s?000/.test(manager)) verdict = { id: String(body.id), verdict: 'OK', correct: null, evidence: [{ source: 'kb', source_version: 'sha256:fixture-kb', record_id: 'steklo-seroe', field: 'цена_за_м2_тг' }] };
      else verdict = { id: String(body.id), verdict: 'NEEDS_REVIEW', correct: null, evidence: [], explanation_ru: 'Фикстура: заготовленного ответа нет — нужна проверка менеджера.', reason_code: 'NO_PRICE_CONTEXT' };
      return ok(verdict);
    }

    // ---------- CRM & analytics ----------
    if (path === '/crm/rank') {
      if (body.policy === 'validated_model') return fail(409, 'MODEL_NOT_PROMOTED', 'Модель не доказала улучшение; зафиксирована reference-v1.');
      const sorted = [...applications].sort((a, b) => Number(b['прошлых_заявок']) - Number(a['прошлых_заявок']) || Number(a['дней_с_последнего_контакта']) - Number(b['дней_с_последнего_контакта']));
      const top = sorted.slice(0, 25);
      const grouped: Record<string, string[]> = {};
      for (const row of top) (grouped[row.client_id] ??= []).push(row.app_id);
      return ok({
        rows: top.map((row, index) => ({ app_id: row.app_id, client_id: row.client_id, priority: 25 - index, reasons: [`Прошлых заявок: ${row['прошлых_заявок']}`, `Дней с контакта: ${row['дней_с_последнего_контакта']}`, 'Фикстура: синтетические заявки'] })),
        unique_client_count: Object.keys(grouped).length,
        policy: 'reference',
        observed_precision: null,
        policy_version: 'reference-v1 (fixture)',
        grouped_clients: grouped,
        target_definition: 'Новое обращение в течение 60 дней; не покупка и не выручка',
      });
    }
    if (path === '/crm/applications') {
      let rows = applications;
      if (q.client_id) rows = rows.filter(row => row.client_id === q.client_id);
      const offset = Number(q.offset ?? 0);
      const limit = Number(q.limit ?? 50);
      return ok({ total: rows.length, offset, rows: rows.slice(offset, offset + limit) });
    }
    if (path === '/crm/reminders' && method === 'GET') {
      const list = state.reminders[datasetId!] ?? [];
      for (const item of list) refreshReminder(item, datasetId!);
      return ok(list);
    }
    if (path === '/crm/reminders' && method === 'POST') {
      const list = (state.reminders[datasetId!] ??= []);
      const duplicate = list.find(item => item.recipient_client_id === body.recipient_client_id && item.subject_type === body.subject_type && item.subject_ref === body.subject_ref && ['draft', 'scheduled', 'due'].includes(item.state));
      if (duplicate) return ok(duplicate);
      if (body.subject_type === 'specific_remnant') {
        const r = state.remnants[datasetId!].find(item => item.remnant_id === body.subject_ref);
        if (!r) return fail(422, 'SUBJECT_NOT_FOUND', 'Остаток не найден.', { field_errors: [{ field: 'body.subject_ref', reason: 'Такого остатка нет в наборе' }] });
      }
      const reminder: Reminder = { ...(body as unknown as Reminder), reminder_id: nextId('REM'), version: 0, state: 'draft', stale_reason: null };
      list.push(reminder);
      return ok(reminder);
    }
    if (seg[0] === 'crm' && seg[1] === 'reminders' && seg.length >= 3) {
      const reminder = (state.reminders[datasetId!] ?? []).find(item => item.reminder_id === seg[2]);
      if (!reminder) return fail(404, 'REMINDER_NOT_FOUND', 'Задача не найдена.');
      refreshReminder(reminder, datasetId!);
      if (method === 'GET') return ok(reminder);
      if (body.expected_version !== reminder.version) return fail(409, 'VERSION_CONFLICT', 'Задача изменена в другом окне.', { conflict_objects: [reminder.reminder_id] });
      const action = seg[3] ?? (method === 'PATCH' ? 'update' : '');
      if (action === 'confirm') {
        if (reminder.state === 'stale') return fail(409, 'SUBJECT_STALE', 'Предмет устарел; закройте задачу или создайте новую.', { conflict_objects: [reminder.reminder_id] });
        reminder.state = 'scheduled';
      } else if (action === 'cancel') reminder.state = 'cancelled';
      else if (body.state === 'done') reminder.state = 'done';
      reminder.version += 1;
      return ok(reminder);
    }
    if (path === '/analytics/managers') return ok(fixtureMetrics(q));

    // ---------- sales ----------
    if (path === '/buyers/registries') return ok([{ version: 'fixture-registry-1', count: data.buyers.length, note: 'ТЕСТОВЫЙ реестр' }]);
    if (path === '/buyers') {
      if (q.version !== 'fixture-registry-1') return fail(404, 'REGISTRY_NOT_FOUND', 'Реестр не найден.');
      return ok(data.buyers);
    }
    if (path === '/buyers/import') return ok({ version: 'fixture-registry-1', count: data.buyers.length });
    if (path === '/sale-cards' && method === 'GET') return ok(state.cards[datasetId!] ?? []);
    if (path === '/sale-cards' && method === 'POST') {
      const plan = state.plans[datasetId!].find(item => item.plan_id === body.plan_id);
      if (!plan) return fail(404, 'PLAN_NOT_FOUND', 'План не найден.');
      const free = plan.free_original_remnant_ids.slice(0, 5);
      if (free.length < 5) return fail(409, 'NOT_ENOUGH_FREE_REMNANTS', 'Меньше пяти свободных исходных кусков в выбранном плане.');
      const factor = String(body.factor ?? '0.50');
      const cards: SaleCard[] = free.map((id, index) => {
        const r = state.remnants[datasetId!].find(item => item.remnant_id === id)!;
        const top = [0, 1, 2].map(offset => data.buyers[(index + offset) % data.buyers.length]);
        return {
          card_id: nextId('CARD'),
          dataset_id: datasetId!,
          remnant_id: id,
          title: `ТЕСТ: ${r.material_id} ${r.dimensions.length_mm}×${r.dimensions.width_mm} мм`,
          price_tg: fixturePrice(r, factor),
          description: `Фикстура: целый исходный кусок, ${r.dimensions.length_mm}×${r.dimensions.width_mm} мм, место ${r.location_raw}.`,
          target_buyer: top[0].name,
          top3_buyers: top.map(buyer => buyer.name),
          top3_buyer_ids: top.map(buyer => buyer.buyer_id as string),
          status: 'ready',
          factor,
          plan_id: plan.plan_id,
          plan_revision: plan.revision,
          remnant_version: r.version ?? 0,
          buyer_registry_version: 'fixture-registry-1',
          version: 0,
          assumptions: 'Коэффициент - проектное допущение, не рыночная оценка и не факт продажи',
        };
      });
      state.cards[datasetId!] = cards;
      return ok(cards);
    }
    if (seg[0] === 'sale-cards' && seg.length === 2 && method === 'PATCH') {
      const card = (state.cards[datasetId!] ?? []).find(item => item.card_id === seg[1]);
      if (!card) return fail(404, 'CARD_NOT_FOUND', 'Карточка не найдена.');
      if (body.expected_version !== card.version) return fail(409, 'VERSION_CONFLICT', 'Карточка изменена.', { conflict_objects: [String(card.card_id)] });
      if (card.status === 'stale') return fail(409, 'STALE_CARD', 'Карточка устарела; создайте новую после пересчета.');
      const r = state.remnants[datasetId!].find(item => item.remnant_id === card.remnant_id)!;
      card.factor = String(body.factor);
      card.price_tg = fixturePrice(r, card.factor);
      card.version = (card.version ?? 0) + 1;
      return ok(card);
    }
    if (seg[0] === 'sale-cards' && seg[2] === 'recheck') {
      const card = (state.cards[datasetId!] ?? []).find(item => item.card_id === seg[1]);
      if (!card) return fail(404, 'CARD_NOT_FOUND', 'Карточка не найдена.');
      return ok(card);
    }

    return fail(501, 'FIXTURE_NOT_DEFINED', `Фикстура не описывает ${method} ${path}. Это тестовый адаптер: результат не выдумывается.`);
  }

  function refreshReminder(reminder: Reminder, datasetId: string) {
    if (reminder.subject_type !== 'specific_remnant' || ['done', 'cancelled'].includes(reminder.state)) return;
    const r = state.remnants[datasetId].find(item => item.remnant_id === reminder.subject_ref);
    if (!r || r.status !== 'available') {
      reminder.state = 'stale';
      reminder.stale_reason = `Остаток ${reminder.subject_ref} больше не свободен`;
    }
  }

  function cannedQuote(quoteId: string, revision: number, body: Body): Quote {
    const dims = body.dimensions as { length_mm: number; width_mm: number } | null | undefined;
    const qty = Number(body.quantity ?? 1);
    const processing = (body.processing as { kind?: string } | undefined)?.kind ?? 'none';
    const product = String(body.catalog_product_id);
    const evidence = [{ source: 'kb', source_version: 'sha256:fixture-kb', record_id: product, field: 'цена' }];
    const base = { dataset_id: String(body.dataset_id), quote_id: quoteId, revision, preliminary: true, customer_id: (body.customer_id as string | null) ?? null, dimensions: dims ?? null, quantity: qty, catalog_product_id: product, kb_version: 'sha256:fixture-kb', evidence };
    // Canned answers for the case scenario only (T28 numbers from the specification).
    const table: Record<string, [string, string, string]> = {
      '450x370x1': ['1332.00', '656.00', '1988.00'],
      '451x370x1': ['1334.96', '656.80', '1991.76'],
      '450x370x2': ['2664.00', '1312.00', '3976.00'],
    };
    let quote: Quote;
    const key = dims ? `${dims.length_mm}x${dims.width_mm}x${qty}` : '';
    if (product === 'steklo-6-prozrachnoe' && processing === 'euro_edge' && table[key]) {
      const [glass, edge, total] = table[key];
      const r = state.remnants[String(body.dataset_id)]?.find(item => item.remnant_id === 'R006');
      const fits = dims!.length_mm <= 450 && dims!.width_mm <= 370 && qty === 1 && r?.status === 'available';
      quote = {
        ...base,
        status: 'calculated',
        components: [
          { label: 'Стекло 6 мм прозрачное', amount_tg: glass, evidence, component: 'glass', formula: `${dims!.length_mm}×${dims!.width_mm}/1 000 000 м² × 8 000 ₸ × ${qty}` },
          { label: 'Евро-кромка 6 мм, 4 стороны', amount_tg: edge, evidence, component: 'edge', formula: `2×(${dims!.length_mm}+${dims!.width_mm})/1000 м × 400 ₸ × ${qty}` },
        ],
        total_tg: total,
        clarification: null,
        material_mapping_status: 'confirmed',
        material_id: 'clear-6',
        product_name: 'Стекло 6 мм прозрачное',
        processing: body.processing as Quote['processing'],
        rounding_policy: 'ROUND_HALF_UP до 0,01 по позициям; итог = сумма позиций',
        inventory_status: body.inventory_mode && body.inventory_mode !== 'none' ? 'checked' : 'not_requested',
        candidate_refs: fits && r ? [{ remnant_id: 'R006', remnant_version: r.version ?? 0, x_mm: 5, y_mm: 5, rot: 0, location_raw: r.location_raw }] : [],
        inventory_reason_codes: fits ? [] : [r?.status !== 'available' ? 'occupied_by_reservation' : 'no_free_whole_remnant'],
      };
    } else if (product === 'steklo-riflenoe-8') {
      quote = { ...base, status: 'needs_review', components: [], total_tg: null, clarification: 'Известна только цена листа 170 000 ₸; ставки за м² нет. Расчет детали дает менеджер.', material_mapping_status: 'unmapped', material_id: null, inventory_status: 'mapping_required', unknown_components: [{ component: 'glass', reason_code: 'PER_M2_PRICE_UNKNOWN', message_ru: 'Ставка за м² отсутствует в KB; известна только цена листа 170 000 ₸.' }] };
    } else {
      quote = { ...base, status: 'needs_review', components: [], total_tg: null, clarification: 'Фикстура: для этих параметров нет заготовленного ответа.', material_mapping_status: 'ambiguous', material_id: null };
    }
    state.quotes[quoteId] = quote;
    return quote;
  }

  function createJob(kind: string, extra: Partial<Job>): Job {
    const job = { job_id: nextId(`job-${kind}`), state: 'queued' as const, stage: 'В очереди', completed: 0, total: kind === 'run' ? 5 : null, cancel_requested: false, stopped: false, polls: 0, kind, elapsed_seconds: 0, budget_seconds: kind === 'solve' ? 60 : 1200, ...extra };
    state.jobs[job.job_id] = job;
    return job;
  }

  function advanceJob(job: State['jobs'][string]) {
    if (['completed', 'failed', 'cancelled', 'interrupted'].includes(job.state)) return;
    job.elapsed_seconds = job.polls;
    if (job.cancel_requested && job.polls > 1) {
      job.state = 'cancelled';
      job.stopped = true;
      job.stage = 'Остановлено пользователем; сохранен последний валидный результат';
      return;
    }
    if (job.kind === 'solve') {
      const stages = ['Проверка допустимости', 'Первый план (Guillotine/MaxRects)', 'Пул шаблонов', 'Глобальный выбор MILP', 'Финализация и независимая проверка'];
      job.state = job.polls >= stages.length ? 'completed' : 'running';
      job.stage = stages[Math.min(job.polls, stages.length) - 1] ?? stages[0];
      const datasetId = job.dataset_id!;
      if (job.polls >= 2 && !job.last_valid_result_ref) {
        const list = state.plans[datasetId];
        const base = list[0];
        const candidate: CutPlan = { ...base, plan_id: nextId('PLAN'), revision: base.revision + 1, status: 'validated', metrics: { ...base.metrics, covered_area_mm2: base.metrics.covered_area_mm2 + 120_000, coverage: 0.5823 } };
        list.push(candidate);
        job.last_valid_result_ref = candidate.plan_id;
      }
      if (job.state === 'completed') job.result_ref = job.last_valid_result_ref;
      return;
    }
    if (job.kind === 'run') {
      const run = state.runs[job.run_id!];
      const pending = run?.jobs.filter(item => item.state === 'queued' || item.state === 'running') ?? [];
      job.state = pending.length ? 'running' : 'completed';
      job.total = run?.jobs.length ?? null;
      job.completed = (run?.jobs.length ?? 0) - pending.length;
      job.stage = pending.length ? `Модули: ${job.completed} из ${job.total}` : 'Все модули завершены (успешно или с ошибкой)';
      return;
    }
    // module jobs advance via GET /runs/{id}
  }

  const inner: Transport = {
    kind: 'fixture',
    async request(req) {
      await new Promise(resolve => setTimeout(resolve, 60));
      if (req.signal?.aborted) throw new TransportFailure('Запрос отменен', 'aborted');
      if (state.offline) throw new TransportFailure('Нет связи', 'offline');
      const failure = state.failures.findIndex(item => req.path.startsWith(item.prefix));
      if (failure >= 0) {
        const [item] = state.failures.splice(failure, 1);
        return fail(item.status, item.code, `Фикстура: смоделирована ошибка ${item.status}.`, { retryable: item.status === 429 || item.status === 503 });
      }
      const idem = req.headers['Idempotency-Key'];
      const hash = JSON.stringify(req.body ?? null);
      if (idem) {
        const scoped = `${req.path}:${idem}`;
        const previous = state.idempotency.get(scoped);
        if (previous) return previous.hash === hash ? previous.response : fail(409, 'IDEMPOTENCY_KEY_REUSED', 'Тот же ключ с другим телом запроса.');
        const response = route(req);
        if (response.status < 300) state.idempotency.set(scoped, { hash, response });
        return response;
      }
      return route(req);
    },
  };
  // Like a real network, never hand out references to the fixture's internal state.
  return {
    kind: 'fixture',
    async request(req) {
      const response = await inner.request(req);
      return { ...response, body: response.body instanceof Blob ? response.body : structuredClone(response.body) };
    },
  };
}

function fixtureMetrics(q: TransportRequest['query'] = {}): ManagerMetrics[] {
  const rows = data.makeApplications().filter(row => {
    if (q.product_group && row['группа_товара'] !== q.product_group) return false;
    if (q.channel && row['канал'] !== q.channel) return false;
    if (q.client_type && row['тип_клиента'] !== q.client_type) return false;
    if (q.day_from !== undefined && q.day_from !== null && Number(row['день_года']) < Number(q.day_from)) return false;
    if (q.day_to !== undefined && q.day_to !== null && Number(row['день_года']) > Number(q.day_to)) return false;
    return true;
  });
  const managers = q.manager ? [String(q.manager)] : ['M1', 'M2', 'M3', 'M4', 'M5'];
  return managers.map(manager => {
    const mine = rows.filter(row => row.manager === manager);
    const ev = (definition: string, known = mine, numerator: string | null = String(known.length)): MetricEvidence => ({
      numerator,
      denominator: known.length,
      source_app_ids: mine.map(row => row.app_id),
      known_app_ids: known.map(row => row.app_id),
      source_rows: known.map(row => row.source_row),
      total: mine.length,
      completeness: mine.length ? known.length / mine.length : null,
      definition,
    });
    const ratio = (field: string) => {
      const positive = mine.filter(row => row[field] === '1').length;
      return { numerator: positive, denominator: mine.length, value: mine.length ? positive / mine.length : null };
    };
    const sold = mine.filter(row => row['продано'] === '1');
    return {
      manager,
      application_count: mine.length,
      mean_response_minutes: mine.length ? mine.reduce((sum, row) => sum + Number(row['ответ_через_мин']), 0) / mine.length : null,
      conversion: ratio('продано'),
      returns: ratio('вернулся_за_60_дней'),
      mean_sale_tg: sold.length ? '45000.00' : null,
      mean_application_tg: mine.length ? '38250.50' : null,
      complaints: ratio('жалоба'),
      discounts: ratio('скидка'),
      evidence: {
        application_count: ev('Фикстура: число строк после фильтра'),
        mean_response_minutes: ev('Фикстура: среднее ответ_через_мин'),
        conversion: ev('Фикстура: продано=1 / известные', mine, String(ratio('продано').numerator)),
        returns: ev('Фикстура: вернулся_за_60_дней=1 / известные', mine, String(ratio('вернулся_за_60_дней').numerator)),
        mean_sale_tg: ev('Фикстура: среднее сумма_тг по продано=1', sold, '45000.00'),
        mean_application_tg: ev('Фикстура: среднее сумма_тг всех заявок'),
        complaints: ev('Фикстура: жалоба=1 / известные', mine, String(ratio('жалоба').numerator)),
        discounts: ev('Фикстура: скидка=1 / известные', mine, String(ratio('скидка').numerator)),
      },
      source_manager_values: [manager],
    };
  });
}

/** Fixture-only price: integer arithmetic in tiyn so test numbers are exact (not product logic). */
function fixturePrice(remnant: Remnant, factor: string): string {
  const rate = BigInt(data.materials.find(item => item.material_id === remnant.material_id)?.unit_price_tg ?? '0');
  const [whole, frac = ''] = factor.split('.');
  const factorHundredths = BigInt(whole) * 100n + BigInt((frac + '00').slice(0, 2));
  const area = BigInt(remnant.dimensions.length_mm * remnant.dimensions.width_mm);
  // tiyn = area/1e6 × rate × factor/100 × 100 → area × rate × factor / 1e6, half-up
  const numerator = area * rate * factorHundredths;
  const tiyn = (numerator + 500_000n) / 1_000_000n;
  return `${tiyn / 100n}.${String(tiyn % 100n).padStart(2, '0')}`;
}

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
  ProposedRun,
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
  runs: Record<string, ProposedRun>;
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
    if (path === '/ready') return ok({ status: 'degraded', database: true, business_modules_ready: false, ai_available: !state.aiOffline && state.settings.secret_present });
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
      const modules = (body.modules as string[]) ?? [];
      state.runs[runId] = {
        run_id: runId,
        dataset_id: dataset.dataset_id,
        status: 'running',
        created_at: new Date().toISOString(),
        modules: modules.map(module => ({ module: module as ProposedRun['modules'][number]['module'], state: 'queued', job_id: null, output_file: null, row_count: null, self_check: null, errors: [] })),
        manifest: null,
        files: [],
        official_scores_available: false,
      };
      return ok(createJob('run', { run_id: runId, dataset_id: dataset.dataset_id }));
    }
    if (seg[0] === 'runs' && seg.length === 2) {
      const run = state.runs[seg[1]];
      return run ? ok(run) : fail(404, 'RUN_NOT_FOUND', 'Прогон не найден.');
    }
    if (seg[0] === 'runs' && seg[2] === 'export') {
      const run = state.runs[seg[1]];
      if (!run) return fail(404, 'RUN_NOT_FOUND', 'Прогон не найден.');
      const failed = run.modules.filter(module => module.state !== 'completed');
      const files: Record<string, string> = {};
      for (const module of run.modules.filter(item => item.state === 'completed')) {
        const header = { cutting: 'part_id,remnant_id,x_mm,y_mm,rot', assistant: 'id,answer', crm: 'app_id', quality: 'id,verdict,correct', cards: 'remnant_id,title,price_tg,description,target_buyer,top3_buyers' }[module.module];
        const name = module.output_file ?? `${module.module}.csv`;
        files[name] = URL.createObjectURL(new Blob([`${header}\n`], { type: 'text/csv' }));
      }
      return ok({ run_id: run.run_id, status: failed.length ? 'partial' : 'ready', files, errors: failed.map(module => `${module.module}: ${module.errors.join('; ') || module.state}`) });
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
    if (path === '/settings/ai/check') return ok({ available: false, provider: state.settings.provider, model_id: state.settings.model_id || null, mode: state.settings.mode, message_ru: 'Фикстура: реальный провайдер не вызывается. Live-проверка выполняется только с настоящим backend и ключом.' });
    if (path === '/system/backups') return ok(state.backups);
    if (path === '/system/backup') {
      const info = { backup_id: nextId('backup'), created_at: new Date().toISOString(), size_bytes: 530000, integrity: 'ok' };
      state.backups.unshift(info);
      return ok(info);
    }
    if (path === '/system/restore') return ok({ restored: true, previous_backup_id: nextId('backup-before-restore') });
    if (path === '/system/shutdown') return ok({ stopping: true });
    if (path === '/system/journal')
      return ok([
        { at: '2026-11-27T05:00:00Z', level: 'info', event: 'startup', detail: 'Фикстура: запуск интерфейса', correlation_id: null },
        { at: '2026-11-27T05:01:00Z', level: 'info', event: 'migrations', detail: 'Фикстура: схема актуальна', correlation_id: null },
      ]);

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
      const changed = body.changed_fields as Body;
      return ok(cannedQuote(quote.quote_id, quote.revision + 1, { ...changed, customer_id: quote.customer_id, dataset_id: datasetId }));
    }
    if (seg[0] === 'quotes' && seg[2] === 'confirm') {
      const blocked = mutableOnly();
      if (blocked) return blocked;
      const quote = state.quotes[seg[1]];
      if (!quote) return fail(404, 'QUOTE_NOT_FOUND', 'Расчет не найден.');
      if (body.remnant_id) {
        const r = state.remnants[datasetId!].find(item => item.remnant_id === body.remnant_id);
        if (!r || r.version !== body.expected_remnant_version || r.status !== 'available')
          return fail(409, 'REMNANT_CONFLICT', 'Остаток уже изменен или занят. Показано актуальное состояние.', { conflict_objects: [String(body.remnant_id)] });
        r.status = 'reserved';
        r.version = (r.version ?? 0) + 1;
      }
      quote.status = 'confirmed';
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
        confirmed_parameters: dims ? { catalog_product_id: 'steklo-6-prozrachnoe', length_mm: dims[1], width_mm: dims[2] } : {},
        assumptions: dims ? ['количество 1 шт — не подтверждено клиентом'] : [],
        tool_calls: [{ tool: 'search_catalog', status: 'ok' }],
      };
      return ok(reply);
    }
    if (seg[0] === 'assistant' && seg[1] === 'conversations') return fail(404, 'CONVERSATION_NOT_FOUND', 'Диалог не найден.');
    if (path === '/quality/check') {
      const manager = String(body.manager);
      let verdict: DialogVerdict;
      if (/10\s?050/.test(manager)) verdict = { id: String(body.id), verdict: 'ERROR', correct: '10000', evidence: [{ source: 'kb', source_version: 'sha256:fixture-kb', record_id: 'steklo-seroe', field: 'цена_за_м2_тг' }], explanation: 'Фикстура: в ответе 10 050 ₸, в KB 10 000 ₸/м².', extracted_value_tg: '10050' };
      else if (/10\s?000/.test(manager)) verdict = { id: String(body.id), verdict: 'OK', correct: null, evidence: [{ source: 'kb', source_version: 'sha256:fixture-kb', record_id: 'steklo-seroe', field: 'цена_за_м2_тг' }] };
      else verdict = { id: String(body.id), verdict: 'NEEDS_REVIEW', correct: null, evidence: [], explanation: 'Фикстура: заготовленного ответа нет — нужна проверка менеджера.' };
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
    if (path === '/buyers') return ok(data.buyers);
    if (path === '/sale-cards' && method === 'GET') return ok(state.cards[datasetId!] ?? []);
    if (path === '/sale-cards' && method === 'POST') {
      const plan = state.plans[datasetId!].find(item => item.plan_id === body.plan_id);
      if (!plan) return fail(404, 'PLAN_NOT_FOUND', 'План не найден.');
      const free = plan.free_original_remnant_ids.slice(0, 5);
      if (free.length < 5) return fail(409, 'NOT_ENOUGH_FREE_REMNANTS', 'Меньше пяти свободных исходных кусков в выбранном плане.');
      const cards: SaleCard[] = free.map((id, index) => {
        const r = state.remnants[datasetId!].find(item => item.remnant_id === id)!;
        return {
          card_id: nextId('CARD'),
          remnant_id: id,
          title: `ТЕСТ: ${r.material_id} ${r.dimensions.length_mm}×${r.dimensions.width_mm} мм`,
          price_tg: ['1234.50', '987.00', '456.75', '2100.00', '3999.99'][index],
          description: `Фикстура: целый исходный кусок, место ${r.location_raw}.`,
          target_buyer: data.buyers[index % data.buyers.length].category,
          top3_buyers: [0, 1, 2].map(offset => data.buyers[(index + offset) % data.buyers.length].name),
          status: 'ready',
          material_id: r.material_id,
          dimensions: r.dimensions,
          location_raw: r.location_raw,
          discount_factor: '0.50',
          material_valuation_tg: ['2469.00', '1974.00', '913.50', '4200.00', '7999.98'][index],
          plan_id: plan.plan_id,
          plan_revision: plan.revision,
          version: 0,
        };
      });
      state.cards[datasetId!] = cards;
      return ok(cards);
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
      quote = { ...base, status: 'calculated', components: [{ label: 'Стекло 6 мм прозрачное', amount_tg: glass, evidence }, { label: 'Евро-кромка 6 мм, 4 стороны', amount_tg: edge, evidence }], total_tg: total, clarification: null, material_mapping_status: 'confirmed', material_id: 'clear-6', rounding_policy: 'ROUND_HALF_UP до 0,01 по позициям' };
    } else if (product === 'steklo-riflenoe-8') {
      quote = { ...base, status: 'needs_review', components: [], total_tg: null, clarification: 'Известна только цена листа 170 000 ₸; ставки за м² нет. Расчет детали дает менеджер.', material_mapping_status: 'unmapped', material_id: null, unknown_fields: ['цена_за_м2_тг'] };
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
      job.state = 'running';
      const index = job.polls - 1;
      if (run && index < run.modules.length) {
        const module = run.modules[index];
        module.state = module.module === 'assistant' && state.aiOffline ? 'failed' : 'completed';
        module.errors = module.state === 'failed' ? ['AI недоступен: ответы не сформированы'] : [];
        module.output_file = { cutting: 'solution.csv', assistant: 'answers.csv', crm: 'picks.csv', quality: 'verdicts.csv', cards: 'sale_cards.csv' }[module.module];
        module.row_count = module.state === 'completed' ? { cutting: 12, assistant: 18, crm: 25, quality: 8, cards: 5 }[module.module] : null;
        module.self_check = module.state === 'completed' ? 'фикстура: схема и число строк' : null;
        job.completed = index + 1;
        job.stage = `Модуль ${module.module}`;
      }
      if (run && index >= run.modules.length - 1) {
        job.state = 'completed';
        run.status = run.modules.every(module => module.state === 'completed') ? 'ready' : 'partial';
        run.manifest = { run_id: run.run_id, dataset_id: run.dataset_id, config_version: 'contest-v1', note: 'FIXTURE — не настоящий RunManifest' };
        run.files = run.modules.filter(module => module.state === 'completed').map(module => ({ name: module.output_file!, sha256: null, rows: module.row_count, validator: 'не запускался (фикстура)', download_url: null }));
      }
    }
  }

  return {
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

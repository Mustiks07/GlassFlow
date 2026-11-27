/**
 * Transport types. The source of truth is the backend OpenAPI schema generated into
 * packages/contracts/schema.d.ts (`pnpm contracts:generate`). We never hand-edit it.
 *
 * Two kinds of additions live here, each clearly marked:
 *  1. `Additive<...>` — fields already implemented on a sibling branch (GPT Pro
 *     platform branch, commit 9055924) but not yet merged into this branch's schema.
 *     They are optional so the type stays compatible before AND after integration.
 *  2. `Proposed*` — DTOs for operations listed in docs/architecture/API_OPERATIONS.md
 *     whose owner has not published a schema yet. The exact shape is a contract
 *     change request recorded in docs/status/CLAUDE_1_ILYAS.md. After integration
 *     the integrator replaces them with generated types.
 */
import type { components } from '../../../../packages/contracts/schema';

type S = components['schemas'];

export type Health = S['Health'];
export type Readiness = S['Readiness'] & Partial<{ ai_available: boolean; worker: boolean; detail: Record<string, unknown> }>;
export type ApiErrorBody = S['ApiError'];
export type Evidence = S['Evidence'];
export type Dimensions = S['Dimensions'];

// ---------- platform (owner: GPT Pro) ----------
export type Dataset = S['Dataset'] &
  Partial<{
    parent_id: string | null;
    version: number;
    created_at: string | null;
    schema_version: string;
    /** Requested: explicit KB version for quote/catalog calls (Pro + C3). */
    kb_version: string | null;
  }>;

export type ImportPreview = S['ImportPreview'] &
  Partial<{
    /** Requested: per-file summary for the preview table. */
    files: { filename: string; kind: string; sha256: string; row_count: number; accepted: boolean }[];
    duplicate_of_dataset_id: string | null;
  }>;

export interface ImportCommit {
  name: string;
  mode: 'source' | 'contest';
  explicit_copy: boolean;
}

export type JobState = S['Job']['state'];
export type Job = S['Job'] &
  Partial<{
    run_id: string | null;
    dataset_id: string | null;
    cancel_requested: boolean;
    stopped: boolean;
    completed: number;
    total: number | null;
    result: Record<string, unknown> | null;
    last_valid_result: Record<string, unknown> | null;
    /** Requested for the job panel: elapsed and budget in seconds. */
    elapsed_seconds: number | null;
    budget_seconds: number | null;
    kind: string;
  }>;

export type RunModule = 'cutting' | 'assistant' | 'crm' | 'quality' | 'cards';
export type RunRequest = S['RunRequest'];
export type ExportResult = S['ExportResult'];

export interface ProposedRunModuleStatus {
  module: RunModule;
  state: JobState | 'not_started' | 'blocked';
  job_id: string | null;
  output_file: string | null;
  row_count: number | null;
  self_check: string | null;
  errors: string[];
}

/** GET /runs/{id} (owner: GPT Pro). */
export interface ProposedRun {
  run_id: string;
  dataset_id: string;
  status: 'queued' | 'running' | 'ready' | 'partial' | 'blocked' | 'failed';
  created_at: string | null;
  modules: ProposedRunModuleStatus[];
  manifest: Record<string, unknown> | null;
  files: { name: string; sha256: string | null; rows: number | null; validator: string | null; download_url: string | null }[];
  official_scores_available: boolean;
}

export interface AISettings {
  version: number;
  profile: 'direct' | 'judge_gateway' | 'local_limited';
  provider: 'gemini' | 'openrouter';
  model_id: string;
  mode: 'free_only' | 'paid_enabled';
  paid_enabled: boolean;
  monthly_budget_tg: string;
  rpm: number;
  max_parallel: number;
  timeout_seconds: number;
  max_retries: number;
  gateway_url: string | null;
  secret_present: boolean;
  /** Requested: allowed model profile list for the select. */
  allowed_models?: string[];
}

export type SettingsUpdate = AISettings & { api_key?: string | null };

export interface AICheckResult {
  available: boolean;
  provider: string | null;
  model_id: string | null;
  mode: string | null;
  message_ru: string;
  quota?: Record<string, unknown> | null;
}

export interface BackupInfo {
  backup_id: string;
  created_at: string;
  size_bytes?: number;
  integrity?: string;
}

export interface JournalEntry {
  at: string;
  level: string;
  event: string;
  detail: string;
  correlation_id?: string | null;
}

// ---------- cutting (owner: Claude 2) ----------
export type Material = {
  material_id: string;
  name: string;
  thickness_mm: number;
  unit_price_tg: string;
  tempered: boolean;
};
export type Remnant = S['Remnant'] &
  Partial<{
    rack: string | null;
    cell: string | null;
    material_name: string;
    tempered: boolean;
  }>;
export type NewRemnant = S['NewRemnant'];
export type Placement = S['Placement'];
export type CutMetrics = S['CutMetrics'];
export type CutPlan = S['CutPlan'] &
  Partial<{
    parent_plan_id: string | null;
    /** Requested: reasons for parts left NEW, keyed by part_id. */
    new_reasons: Record<string, UnplacedReason>;
    excluded_remnant_ids: string[];
    version: number;
  }>;
export type ValidationResult = S['ValidationResult'] &
  Partial<{ errors_by_part: Record<string, string[]> }>;
export type Candidate = S['Candidate'] & Partial<{ length_mm: number; width_mm: number; material_id: string; tempered: boolean }>;
export type Candidates = S['Candidates'];
export type FindRequest = S['FindRequest'];
export type SolveRequest = S['SolveRequest'];
export type SolverConfig = S['SolverConfig'];
export type CommitPlan = S['CommitPlan'];

export type UnplacedReason =
  | 'material_mismatch'
  | 'size_does_not_fit'
  | 'premium_on_defect'
  | 'occupied_by_reservation'
  | 'lock_conflict'
  | 'search_limited'
  | 'unknown';

export type Part = {
  part_id: string;
  order_id: string;
  material_id: string;
  dimensions: Dimensions;
  premium: boolean;
  product_type: string;
};

/** POST /plans/{id}/draft (owner: Claude 2). */
export interface ProposedPlanDraft {
  dataset_id: string;
  base_revision: number;
  placements: Placement[];
  excluded_remnant_ids: string[];
}

/** POST /plans/compare (owner: Claude 2). */
export interface ProposedPlanComparison {
  base: { plan_id: string; revision: number; metrics: CutMetrics };
  candidate: { plan_id: string; revision: number; metrics: CutMetrics };
  delta_covered_area_mm2: number;
  delta_replacement_value_tg: string;
  delta_fully_covered_orders: number;
  newly_new_part_ids: string[];
  newly_placed_part_ids: string[];
  affected_quote_ids: string[];
  affected_sale_card_ids: string[];
}

export interface ProposedMeasurement {
  dataset_id: string;
  expected_version: number;
  previous_dimensions: Dimensions;
  dimensions: Dimensions;
  reason: string;
}

export interface ProposedConsume {
  dataset_id: string;
  expected_version: number;
  reservation_id: string | null;
  reason: string;
}

// ---------- intelligence (owner: Claude 3) ----------
export type CatalogProduct = S['CatalogProduct'];
export type CatalogPrice = S['CatalogPrice'];
export type Processing = S['Processing'];
export type QuoteRequest = S['QuoteRequest'];
export type QuoteLine = S['QuoteLine'];
export type Quote = S['Quote'] &
  Partial<{
    customer_id: string | null;
    dimensions: Dimensions | null;
    quantity: number;
    catalog_product_id: string;
    kb_version: string;
    candidate_refs: Candidate[];
    unknown_fields: string[];
    rounding_policy: string;
    evidence: Evidence[];
    created_at: string;
    /** Requested: stale reason when KB/inventory version moved. */
    stale_reason: string | null;
  }>;
export type AssistantTurn = S['AssistantTurn'];
export type AssistantReply = S['AssistantReply'] &
  Partial<{
    confirmed_parameters: Record<string, string>;
    assumptions: string[];
    tool_calls: { tool: string; status: string }[];
    candidates: Candidate[];
  }>;
export type DialogRequest = S['DialogRequest'];
export type DialogVerdict = S['DialogVerdict'] & Partial<{ explanation: string; extracted_value_tg: string | null }>;

/** GET /assistant/conversations/{id} (owner: Claude 3). */
export interface ProposedConversation {
  conversation_id: string;
  dataset_id: string;
  customer_id: string | null;
  turns: { role: 'user' | 'assistant'; text: string; at: string | null; clarification?: string | null; quote_id?: string | null }[];
}

export interface ProposedQuoteRevise {
  dataset_id: string;
  expected_revision: number;
  changed_fields: Partial<Pick<QuoteRequest, 'dimensions' | 'quantity' | 'processing' | 'catalog_product_id' | 'kb_version'>>;
}

export interface ProposedQuoteConfirm {
  dataset_id: string;
  expected_revision: number;
  /** When a remnant candidate is reserved together with the quote. */
  remnant_id: string | null;
  expected_remnant_version: number | null;
}

// ---------- CRM & analytics (owner: GPT Pro) ----------
export type RankRequest = S['RankRequest'];
export type RankedApplication = S['RankedApplication'];
export type Ranking = S['Ranking'] &
  Partial<{ policy_version: string; grouped_clients: Record<string, string[]>; target_definition: string }>;
export type ReminderRequest = S['ReminderRequest'] &
  Partial<{ subject_version: number | null; text: string; active_period: string | null }>;
export type Reminder = S['Reminder'] & Partial<{ text: string; stale_reason: string | null; active_period: string | null }>;
export interface ReminderUpdate {
  dataset_id: string;
  expected_version: number;
  due_at?: string | null;
  owner?: string | null;
  text?: string | null;
  state?: 'done' | null;
}
export interface VersionAction {
  dataset_id: string;
  expected_version: number;
}
export interface MetricEvidence {
  numerator: string | null;
  denominator: number;
  source_app_ids: string[];
  known_app_ids: string[];
  source_rows: number[];
  total: number;
  completeness: number | null;
  definition: string;
}
export type Ratio = S['Ratio'];
export type ManagerMetrics = S['ManagerMetrics'] &
  Partial<{ evidence: Record<string, MetricEvidence>; source_manager_values: string[] }>;

export interface ApplicationRow {
  source_row: number;
  app_id: string;
  client_id: string;
  [field: string]: string | number | null;
}
export interface ApplicationsPage {
  total: number;
  offset: number;
  rows: ApplicationRow[];
}

// ---------- sales (owner: GPT Pro) ----------
export type Buyer = S['Buyer'] & Partial<{ buyer_id: string; verified_at: string; registry_version: string }>;
export type CardsRequest = S['CardsRequest'];
export type SaleCard = S['SaleCard'] &
  Partial<{
    card_id: string;
    status: 'draft' | 'checked' | 'ready' | 'stale';
    stale_reason: string | null;
    material_id: string;
    dimensions: Dimensions;
    location_raw: string;
    discount_factor: string;
    material_valuation_tg: string;
    plan_id: string;
    plan_revision: number;
    buyer_evidence: Record<string, string>;
    version: number;
  }>;

/**
 * Transport types. The source of truth is the backend OpenAPI schema generated into
 * packages/contracts/schema.d.ts (`pnpm contracts:generate`). We never hand-edit it.
 *
 * This branch still carries the foundation schema. Two kinds of additions live here:
 *  1. Optional extension fields (`S['X'] & Partial<{...}>`) — fields that the owners have
 *     ALREADY implemented on their branches (checked 27.11.2026: GPT Pro 6512eae,
 *     Claude 3 4616645). They are optional so the type compiles both before and after
 *     the integrator regenerates schema.d.ts from the merged DTOs.
 *  2. `Proposed*` — DTOs for operations from docs/architecture/API_OPERATIONS.md whose
 *     owner has not published a schema yet (mostly Claude 2 cutting). The exact shape is
 *     a contract change request recorded in docs/status/CLAUDE_1_ILYAS.md.
 */
import type { components } from '../../../../packages/contracts/schema';

type S = components['schemas'];

export type Health = S['Health'];
/** Pro 6512eae: schema/worker/ai/modules. */
export type Readiness = S['Readiness'] &
  Partial<{ schema: boolean; worker: boolean; ai: 'unavailable' | 'unchecked' | 'available'; modules: Record<string, boolean> }>;
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
    /** Requested (Pro + C3): explicit KB version for quote/catalog calls. */
    kb_version: string | null;
  }>;

export type ImportPreview = S['ImportPreview'];

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
    kind: string;
    cancel_requested: boolean;
    stopped: boolean;
    completed: number;
    total: number | null;
    result: Record<string, unknown> | null;
    last_valid_result: Record<string, unknown> | null;
    /** Requested for the job panel: elapsed and budget in seconds. */
    elapsed_seconds: number | null;
    budget_seconds: number | null;
  }>;

export type RunModule = 'cutting' | 'assistant' | 'crm' | 'quality' | 'cards';
export type RunRequest = S['RunRequest'] &
  Partial<{
    solver_config: SolverConfig;
    ai_profile: 'direct' | 'judge_gateway' | 'local_limited';
    buyer_registry_version: string | null;
  }>;
/** Pro 6512eae: export returns files as /api/v1/runs/{run}/files/{export}/{name}. */
export type ExportResult = S['ExportResult'] & Partial<{ export_id: string; manifest: Record<string, unknown>; validators: Record<string, unknown> }>;

/** GET /runs/{id} — Pro 6512eae run_view. */
export interface RunView {
  version?: number;
  budget?: Record<string, unknown> | null;
  manifest: Record<string, unknown> & { modules?: RunModule[]; dataset_id?: string };
  status: 'running' | 'completed' | 'partial' | 'blocked';
  jobs: Job[];
  missing_modules: RunModule[];
}

export interface AISettings {
  version: number;
  profile: 'direct' | 'judge_gateway' | 'local_limited';
  provider: 'gemini' | 'openrouter' | 'basisweb';
  included_quota_enabled?: boolean;
  quota_token_budget?: number;
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

/** POST /settings/ai/check — Pro 6512eae. */
export interface AICheckResult {
  available: boolean;
  provider?: string | null;
  model_id?: string | null;
  capabilities?: Record<string, boolean>;
  checked_at?: string;
  message_ru?: string;
}

export interface BackupInfo {
  backup_id: string;
  created_at: string;
  sha256?: string;
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

// ---------- cutting (owner: Claude 2, contracts from 5897472) ----------
export type Material = {
  material_id: string;
  name: string;
  thickness_mm: number;
  unit_price_tg: string;
  tempered: boolean;
};
export type Remnant = S['Remnant'] &
  Partial<{
    internal_id: string | null;
    origin: 'source' | 'working' | 'child';
    original: boolean;
    rack: string | null;
    cell: string | null;
    parent_remnant_id: string | null;
    active_reservation_id: string | null;
    status_reason: string | null;
    tempered: boolean;
  }>;
export type NewRemnant = S['NewRemnant'];
export type Placement = S['Placement'];
export interface PlanIssue {
  code: string;
  message_ru: string;
  part_id?: string | null;
  remnant_id?: string | null;
  other_part_id?: string | null;
  coordinates?: Record<string, number>;
}
export type CutMetrics = S['CutMetrics'] &
  Partial<{
    total_orders: number;
    covered_parts: number;
    total_parts: number;
    used_original_remnants: number;
    free_original_remnants: number;
    coverage_percent: string;
    new_reasons: Record<string, string>;
  }>;
export type CutPlan = Omit<S['CutPlan'], 'metrics'> & { metrics: CutMetrics } &
  Partial<{
    parent_plan_id: string | null;
    parent_revision: number | null;
    stop_reason: string;
    issues: PlanIssue[];
    source: 'solver' | 'edit' | 'import';
    inventory_current: boolean | null;
    /** Older shape kept for compatibility; C2 reports reasons in metrics.new_reasons. */
    new_reasons: Record<string, string>;
  }>;
/** GET /plans → PlanSummary[] (no placements). */
export interface PlanSummary {
  plan_id: string;
  revision: number;
  status: string;
  search_status: string;
  coverage: number;
  created_at?: string | null;
  source: string;
}
export type ValidationResult = S['ValidationResult'] & Partial<{ issues: PlanIssue[]; plan_revision: number | null }>;
export type Candidate = S['Candidate'] &
  Partial<{
    copy_index: number;
    remnant_dimensions: Dimensions | null;
    age_days: number | null;
    shares_remnant_with_plan: boolean;
    tempered: boolean;
  }>;
export type Candidates = S['Candidates'] & Partial<{ reasons_ru: string[]; covered_quantity: number; requested_quantity: number; inventory_version: string }>;
export type FindRequest = S['FindRequest'];
export type SolveRequest = S['SolveRequest'] & Partial<{ excluded_remnant_ids: string[]; mode: 'replan' | 'keep_committed' }>;
export type SolverConfig = S['SolverConfig'];
export type CommitPlan = S['CommitPlan'] & Partial<{ owner_context: string }>;

export type Part = {
  part_id: string;
  order_id: string;
  material_id: string;
  dimensions: Dimensions;
  premium: boolean;
  product_type: string;
};
/** POST /cutting/solve-input — read-only snapshot (used for parts and materials lists). */
export interface SolveInputView {
  dataset_id: string;
  materials: Material[];
  remnants: Remnant[];
  parts: Part[];
}
export interface DraftEdit {
  part_id: string;
  action: 'move' | 'unplace' | 'lock' | 'unlock';
  remnant_id?: string | null;
  x_mm?: number | null;
  y_mm?: number | null;
  rot?: 0 | 1 | null;
  lock_kind?: Placement['lock_kind'] | null;
}
export interface DraftRequest {
  dataset_id: string;
  base_revision: number;
  edits: DraftEdit[];
}
export interface DraftResult {
  plan: CutPlan;
  validation: ValidationResult;
}
export interface Reservation {
  reservation_id: string;
  dataset_id: string;
  remnant_id: string;
  plan_id: string;
  plan_revision: number;
  owner_context: string;
  status: 'active' | 'released' | 'consumed';
  version: number;
  created_at: string;
}
export interface CommitResult {
  plan: CutPlan;
  reservations: Reservation[];
  released_reservation_ids: string[];
  superseded_plan: string | null;
}
export interface InventoryChange {
  remnant: Remnant;
  reservation: Reservation | null;
  audit_event_id: string;
  children: Remnant[];
}
export interface PlanRef {
  plan_id: string;
  revision?: number | null;
}
export interface PlanComparison {
  dataset_id: string;
  base: PlanRef;
  candidate: PlanRef;
  delta_covered_area_mm2: number;
  delta_coverage: number;
  delta_value_tg: string;
  delta_fully_covered_orders: number;
  delta_free_original_remnants: number;
  newly_new_part_ids: string[];
  newly_covered_part_ids: string[];
  changes: { part_id: string; kind: string }[];
  affected_reserved_remnant_ids: string[];
}
export interface ImpactReport {
  dataset_id: string;
  remnant_id: string;
  remnant_version: number;
  plan_id: string | null;
  plan_revision: number | null;
  affected_part_ids: string[];
  new_part_ids: string[];
  delta_covered_area_mm2: number;
  delta_value_tg: string;
  affected_reservation_ids: string[];
  affected_order_ids: string[];
  requires_commit: boolean;
  note_ru: string;
}
export interface FreeRemnantsCheck {
  dataset_id: string;
  plan_id: string;
  revision: number;
  plan_status: string;
  as_of: string;
  free_original: { remnant_id: string; version: number; material_id: string; dimensions: Dimensions; defect: boolean; location_raw: string }[];
  count: number;
  minimum_free_remnants: number;
  minimum_free_remnants_met: boolean;
  no_longer_free_remnant_ids: string[];
}
export interface MeasurementUpdate {
  dataset_id: string;
  expected_version: number;
  dimensions: Dimensions;
  previous_dimensions?: Dimensions | null;
  reason: string;
}
export interface ConsumeRequest {
  dataset_id: string;
  expected_version: number;
  reservation_id: string;
  reason: string;
}
export interface WithdrawRequest {
  dataset_id: string;
  expected_version: number;
  reason: string;
}
export interface ReserveRequest {
  dataset_id: string;
  expected_version: number;
  owner_context: string;
  material_id: string;
  dimensions: Dimensions;
  premium: boolean;
  x_mm?: number | null;
  y_mm?: number | null;
  rot?: 0 | 1 | null;
}
export type UnplacedReason = string;

// ---------- intelligence (owner: Claude 3, contracts from 4616645) ----------
export type MappingStatus = 'confirmed' | 'proposed' | 'ambiguous' | 'unmapped';
export type CatalogPrice = S['CatalogPrice'] & Partial<{ unit: string | null; source_field: string | null }>;
export interface MaterialMapping {
  dataset_id: string;
  catalog_product_id: string;
  material_id: string | null;
  status: MappingStatus;
  basis: string;
  candidate_material_ids: string[];
  confirmed_by: string | null;
  version: number;
  kb_version: string;
}
export type CatalogProduct = Omit<S['CatalogProduct'], 'prices'> & {
  prices: CatalogPrice[];
} & Partial<{ kind: string | null; attributes: Record<string, string>; unknown_fields: Record<string, string>; kb_version: string | null; mapping: MaterialMapping | null }>;
export type Processing = S['Processing'];
export type QuoteRequest = S['QuoteRequest'] &
  Partial<{
    price_basis: 'auto' | 'per_m2' | 'per_sheet' | 'unit';
    inventory_mode: 'none' | 'free_whole_remnants' | 'replan';
    premium: boolean;
    assumptions: string[];
  }>;
export type QuoteLine = S['QuoteLine'] &
  Partial<{
    component: 'glass' | 'sheet' | 'edge' | 'hardware' | null;
    quantity: number | null;
    unit_price_tg: string | null;
    unit: string | null;
    measure_per_unit: string | null;
    exact_amount_tg: string | null;
    formula: string | null;
  }>;
export interface UnknownComponent {
  component: string;
  reason_code: string;
  message_ru: string;
  evidence?: Evidence[];
}
export interface QuoteDiff {
  from_revision: number;
  to_revision: number;
  changed_fields: string[];
  lines: { component: string; before_tg: string | null; after_tg: string | null }[];
  total_before_tg: string | null;
  total_after_tg: string | null;
}
export type QuoteStatus = 'calculated' | 'needs_review' | 'ready' | 'confirmed' | 'superseded' | 'cancelled';
export type Quote = Omit<S['Quote'], 'status' | 'material_mapping_status' | 'components'> & {
  status: QuoteStatus;
  material_mapping_status: MappingStatus;
  components: QuoteLine[];
} & Partial<{
    catalog_product_id: string | null;
    product_name: string | null;
    kb_version: string | null;
    customer_id: string | null;
    dimensions: Dimensions | null;
    quantity: number | null;
    processing: Processing | null;
    price_basis: string | null;
    confirmed_parameters: Record<string, string>;
    assumptions: string[];
    unknown_components: UnknownComponent[];
    known_subtotal_tg: string | null;
    rounding_policy: string;
    source_versions: Record<string, string>;
    inventory_status: 'not_requested' | 'checked' | 'mapping_required' | 'unavailable' | 'service_unavailable';
    candidate_refs: Candidate[];
    inventory_reason_codes: string[];
    stale: boolean;
    created_at: string | null;
    confirmed_at: string | null;
    confirmed_by: string | null;
    diff: QuoteDiff | null;
    evidence: Evidence[];
  }>;

/** POST /quotes/{id}/revise — Claude 3 QuoteReviseRequest. */
export interface QuoteReviseRequest {
  dataset_id: string;
  expected_revision: number;
  changes: Partial<{
    catalog_product_id: string | null;
    dimensions: Dimensions | null;
    quantity: number | null;
    processing: Processing | null;
    price_basis: 'auto' | 'per_m2' | 'per_sheet' | 'unit' | null;
    customer_id: string | null;
    kb_version: string | null;
  }>;
  reprice_current_kb?: boolean;
}

/** POST /quotes/{id}/confirm — Claude 3 QuoteConfirmRequest (does not reserve stock). */
export interface QuoteConfirmRequest {
  dataset_id: string;
  expected_revision: number;
  confirmed_by: string;
}

export type AssistantTurn = S['AssistantTurn'] & Partial<{ inventory_mode: 'none' | 'free_whole_remnants' | 'replan'; allow_ai: boolean }>;
export interface ToolCallRecord {
  tool: string;
  status: 'ok' | 'rejected' | 'error' | 'unavailable';
  arguments?: Record<string, unknown>;
  summary?: string;
  error_code?: string | null;
}
export interface VerifiedFact {
  fact_id: string;
  kind: string;
  value: string;
  unit?: string | null;
  source_ref: string;
  status: 'supported' | 'unsupported' | 'unknown';
}
export interface WorkingCard {
  intent: string;
  catalog_product_id?: string | null;
  product_name?: string | null;
  confirmed_parameters: Record<string, string>;
  assumptions: string[];
  missing_parameters: string[];
  normalized_dimensions?: string | null;
  facts: VerifiedFact[];
  alternatives: string[];
  needs_manager: boolean;
}
export type AssistantReply = Omit<S['AssistantReply'], 'quote'> & { quote?: Quote | null } & Partial<{
    answer_path: 'deterministic' | 'llm_tools' | 'fallback';
    status: 'answered' | 'clarification' | 'manager_handoff' | 'limited';
    card: WorkingCard | null;
    tool_calls: ToolCallRecord[];
    verifier_status: 'supported' | 'unsupported_replaced' | 'not_applicable';
    ai_unavailable_reason: string | null;
    turn_index: number;
    latency_ms: number | null;
  }>;
/** GET /assistant/conversations/{id} — Claude 3 Conversation. */
export interface Conversation {
  conversation_id: string;
  dataset_id: string;
  customer_id: string | null;
  context: Record<string, string>;
  turns: { turn_index: number; user_text: string; reply: AssistantReply; created_at: string }[];
}
export type DialogRequest = S['DialogRequest'];
export type DialogVerdict = S['DialogVerdict'] &
  Partial<{
    catalog_product_id: string | null;
    reference_tg: string | null;
    reference_meaning: string | null;
    mentions: { raw: string; amount_tg: string; meaning: string }[];
    reason_code: string | null;
    explanation_ru: string | null;
  }>;

// ---------- CRM & analytics (owner: GPT Pro) ----------
export type RankRequest = S['RankRequest'];
export type RankedApplication = S['RankedApplication'];
export type Ranking = S['Ranking'] & Partial<{ policy_version: string; grouped_clients: Record<string, string[]>; target_definition: string }>;
export type ReminderRequest = S['ReminderRequest'] & Partial<{ subject_version: number | null; text: string; active_period: string | null }>;
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
export type ManagerMetrics = S['ManagerMetrics'] & Partial<{ evidence: Record<string, MetricEvidence>; source_manager_values: string[] }>;

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

// ---------- sales (owner: GPT Pro, 6512eae) ----------
export type Buyer = S['Buyer'] & Partial<{ buyer_id: string | null }>;
export interface BuyerRegistry {
  version: string;
  [field: string]: unknown;
}
export type CardsRequest = S['CardsRequest'] & Partial<{ factor: string }>;
export type SaleCard = S['SaleCard'] &
  Partial<{
    card_id: string | null;
    dataset_id: string | null;
    plan_id: string | null;
    plan_revision: number | null;
    remnant_version: number | null;
    buyer_registry_version: string | null;
    version: number;
    status: 'draft' | 'ready' | 'stale';
    factor: string;
    top3_buyer_ids: string[];
    assumptions: string;
    stale_reason: string | null;
  }>;
export interface CardUpdate {
  dataset_id: string;
  expected_version: number;
  factor?: string | null;
  top3_buyer_ids?: string[] | null;
}

/**
 * One function per API operation. Names follow docs/architecture/API_OPERATIONS.md.
 * Every domain call carries dataset_id explicitly. Mutations that the contract marks
 * as confirm/commit/consume/export require an idempotency key from the caller.
 */
import type { ApiClient } from './client';
import type * as T from './types';

const enc = encodeURIComponent;

export function createEndpoints(api: ApiClient) {
  return {
    // ----- platform -----
    health: (signal?: AbortSignal) => api.get<T.Health>('/health', { signal, timeoutMs: 8_000 }),
    ready: (signal?: AbortSignal) => api.get<T.Readiness>('/ready', { signal, timeoutMs: 8_000 }),
    listDatasets: (signal?: AbortSignal) => api.get<T.Dataset[]>('/datasets', { signal, query: { limit: 200 } }),
    getDataset: (datasetId: string, signal?: AbortSignal) => api.get<T.Dataset>(`/datasets/${enc(datasetId)}`, { signal }),
    createWorkingCopy: (datasetId: string, name: string, idempotencyKey: string) =>
      api.post<T.Dataset>(`/datasets/${enc(datasetId)}/working-copy`, { name }, { idempotencyKey }),
    previewImport: (files: File[]) => {
      const form = new FormData();
      for (const file of files) form.append('files', file, file.name);
      return api.request<T.ImportPreview>('POST', '/imports/preview', { form, timeoutMs: 120_000 }).then(result => result.data);
    },
    commitImport: (importId: string, body: T.ImportCommit, idempotencyKey: string) =>
      api.post<T.Dataset>(`/imports/${enc(importId)}/commit`, body, { idempotencyKey }),

    getJob: (jobId: string, signal?: AbortSignal) => api.get<T.Job>(`/jobs/${enc(jobId)}`, { signal }),
    cancelJob: (jobId: string) => api.post<T.Job>(`/jobs/${enc(jobId)}/cancel`),

    createRun: (body: T.RunRequest, idempotencyKey: string) => api.post<T.Job>('/runs', body, { idempotencyKey }),
    getRun: (runId: string, signal?: AbortSignal) => api.get<T.ProposedRun>(`/runs/${enc(runId)}`, { signal }),
    exportRun: (runId: string, idempotencyKey: string) =>
      api.post<T.ExportResult>(`/runs/${enc(runId)}/export`, undefined, { idempotencyKey, timeoutMs: 120_000 }),

    getSettings: (signal?: AbortSignal) => api.get<T.AISettings>('/settings', { signal }),
    updateSettings: (body: T.SettingsUpdate) => api.patch<T.AISettings>('/settings', body),
    checkAi: () => api.post<T.AICheckResult>('/settings/ai/check', {}, { timeoutMs: 60_000 }),
    backup: (reason: string, idempotencyKey: string) => api.post<T.BackupInfo>('/system/backup', { reason }, { idempotencyKey }),
    listBackups: (signal?: AbortSignal) => api.get<T.BackupInfo[]>('/system/backups', { signal }),
    restore: (backupId: string, idempotencyKey: string) =>
      api.post<{ restored: boolean; previous_backup_id?: string }>(
        '/system/restore',
        { backup_id: backupId, confirm_replace: true },
        { idempotencyKey },
      ),
    shutdown: (reason: string) => api.post<{ stopping: boolean }>('/system/shutdown', { reason }),
    journal: (signal?: AbortSignal) => api.get<T.JournalEntry[]>('/system/journal', { signal }),

    // ----- cutting (Claude 2) -----
    listRemnants: (datasetId: string, signal?: AbortSignal) =>
      api.get<T.Remnant[]>('/remnants', { signal, query: { dataset_id: datasetId, limit: 200 } }),
    addRemnant: (body: T.NewRemnant, idempotencyKey: string) => api.post<T.Remnant>('/remnants', body, { idempotencyKey }),
    measureRemnant: (remnantId: string, body: T.ProposedMeasurement, idempotencyKey: string) =>
      api.patch<T.Remnant>(`/remnants/${enc(remnantId)}/measurement`, body, { idempotencyKey }),
    consumeRemnant: (remnantId: string, body: T.ProposedConsume, idempotencyKey: string) =>
      api.post<T.Remnant>(`/remnants/${enc(remnantId)}/consume`, body, { idempotencyKey }),
    releaseRemnant: (remnantId: string, body: T.ProposedConsume, idempotencyKey: string) =>
      api.post<T.Remnant>(`/remnants/${enc(remnantId)}/release`, body, { idempotencyKey }),
    listParts: (datasetId: string, signal?: AbortSignal) =>
      api.get<T.Part[]>('/cutting/parts', { signal, query: { dataset_id: datasetId } }),
    listMaterials: (datasetId: string, signal?: AbortSignal) =>
      api.get<T.Material[]>('/cutting/materials', { signal, query: { dataset_id: datasetId } }),
    listPlans: (datasetId: string, signal?: AbortSignal) =>
      api.get<T.CutPlan[]>('/plans', { signal, query: { dataset_id: datasetId } }),
    findCandidates: (body: T.FindRequest, signal?: AbortSignal) => api.post<T.Candidates>('/cutting/candidates', body, { signal }),
    solve: (body: T.SolveRequest, idempotencyKey: string) => api.post<T.Job>('/cutting/solve', body, { idempotencyKey }),
    getPlan: (planId: string, datasetId: string, signal?: AbortSignal) =>
      api.get<T.CutPlan>(`/plans/${enc(planId)}`, { signal, query: { dataset_id: datasetId } }),
    saveDraft: (planId: string, body: T.ProposedPlanDraft) => api.post<T.CutPlan>(`/plans/${enc(planId)}/draft`, body),
    validatePlan: (planId: string, datasetId: string, revision?: number) =>
      api.post<T.ValidationResult>(`/plans/${enc(planId)}/validate`, undefined, { query: { dataset_id: datasetId, revision } }),
    commitPlan: (planId: string, body: T.CommitPlan, idempotencyKey: string) =>
      api.post<T.CutPlan>(`/plans/${enc(planId)}/commit`, body, { idempotencyKey }),
    comparePlans: (body: { dataset_id: string; base_plan_id: string; candidate_plan_id: string }) =>
      api.post<T.ProposedPlanComparison>('/plans/compare', body),

    // ----- intelligence (Claude 3) -----
    listCatalog: (datasetId: string, kbVersion: string, signal?: AbortSignal) =>
      api.get<T.CatalogProduct[]>('/catalog', { signal, query: { dataset_id: datasetId, kb_version: kbVersion } }),
    calculateQuote: (body: T.QuoteRequest) => api.post<T.Quote>('/quotes', body),
    getQuote: (quoteId: string, datasetId: string, signal?: AbortSignal) =>
      api.get<T.Quote>(`/quotes/${enc(quoteId)}`, { signal, query: { dataset_id: datasetId } }),
    reviseQuote: (quoteId: string, body: T.ProposedQuoteRevise, idempotencyKey: string) =>
      api.post<T.Quote>(`/quotes/${enc(quoteId)}/revise`, body, { idempotencyKey }),
    confirmQuote: (quoteId: string, body: T.ProposedQuoteConfirm, idempotencyKey: string) =>
      api.post<T.Quote>(`/quotes/${enc(quoteId)}/confirm`, body, { idempotencyKey }),
    assistantTurn: (body: T.AssistantTurn, signal?: AbortSignal) =>
      api.post<T.AssistantReply>('/assistant/turns', body, { signal, timeoutMs: 45_000 }),
    getConversation: (conversationId: string, datasetId: string, signal?: AbortSignal) =>
      api.get<T.ProposedConversation>(`/assistant/conversations/${enc(conversationId)}`, { signal, query: { dataset_id: datasetId } }),
    checkDialog: (body: T.DialogRequest) => api.post<T.DialogVerdict>('/quality/check', body, { timeoutMs: 45_000 }),

    // ----- CRM & analytics (GPT Pro) -----
    rank: (body: T.RankRequest) => api.post<T.Ranking>('/crm/rank', body),
    applications: (datasetId: string, query: { client_id?: string; offset?: number; limit?: number }, signal?: AbortSignal) =>
      api.get<T.ApplicationsPage>('/crm/applications', { signal, query: { dataset_id: datasetId, ...query } }),
    listReminders: (datasetId: string, signal?: AbortSignal) =>
      api.get<T.Reminder[]>('/crm/reminders', { signal, query: { dataset_id: datasetId, limit: 200 } }),
    getReminder: (reminderId: string, datasetId: string, signal?: AbortSignal) =>
      api.get<T.Reminder>(`/crm/reminders/${enc(reminderId)}`, { signal, query: { dataset_id: datasetId } }),
    createReminder: (body: T.ReminderRequest, idempotencyKey: string) =>
      api.post<T.Reminder>('/crm/reminders', body, { idempotencyKey }),
    updateReminder: (reminderId: string, body: T.ReminderUpdate, idempotencyKey: string) =>
      api.patch<T.Reminder>(`/crm/reminders/${enc(reminderId)}`, body, { idempotencyKey }),
    confirmReminder: (reminderId: string, body: T.VersionAction, idempotencyKey: string) =>
      api.post<T.Reminder>(`/crm/reminders/${enc(reminderId)}/confirm`, body, { idempotencyKey }),
    cancelReminder: (reminderId: string, body: T.VersionAction, idempotencyKey: string) =>
      api.post<T.Reminder>(`/crm/reminders/${enc(reminderId)}/cancel`, body, { idempotencyKey }),
    managerMetrics: (
      datasetId: string,
      filters: { manager?: string; product_group?: string; channel?: string; client_type?: string; day_from?: number; day_to?: number },
      signal?: AbortSignal,
    ) => api.get<T.ManagerMetrics[]>('/analytics/managers', { signal, query: { dataset_id: datasetId, ...filters } }),

    // ----- sales (GPT Pro) -----
    listBuyers: (signal?: AbortSignal) => api.get<T.Buyer[]>('/buyers', { signal }),
    createSaleCards: (body: T.CardsRequest, idempotencyKey: string) =>
      api.post<T.SaleCard[]>('/sale-cards', body, { idempotencyKey }),
    listSaleCards: (datasetId: string, signal?: AbortSignal) =>
      api.get<T.SaleCard[]>('/sale-cards', { signal, query: { dataset_id: datasetId } }),
    recheckSaleCard: (cardId: string, datasetId: string) =>
      api.post<T.SaleCard>(`/sale-cards/${enc(cardId)}/recheck`, { dataset_id: datasetId }),
  };
}

export type Endpoints = ReturnType<typeof createEndpoints>;

/**
 * Local UI state only (Zustand). Server state lives in TanStack Query.
 * Persisted: selected dataset and unsent form drafts, so a refresh/restart does not
 * lose user input. Secrets (API keys) are never placed in this store.
 */
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export interface QuoteDraft {
  request: string;
  catalogProductId: string;
  length: string;
  width: string;
  quantity: string;
  priceBasis?: 'auto' | 'per_m2' | 'per_sheet' | 'unit';
  processing: 'none' | 'euro_edge' | 'facet' | 'sandblast';
  sides: 'all' | 'selected';
  selectedSides: ('left' | 'right' | 'top' | 'bottom')[];
  customerId: string;
  conversationId: string | null;
  quoteId: string | null;
}

export interface ReminderDraft {
  recipientClientId: string;
  sourceAppIds: string[];
  subjectType: 'interest' | 'quote_example' | 'specific_remnant';
  subjectRef: string;
  subjectVersion: string;
  dueAt: string;
  owner: string;
  text: string;
}

export const emptyQuoteDraft: QuoteDraft = {
  request: '',
  catalogProductId: '',
  length: '',
  width: '',
  quantity: '1',
  priceBasis: 'auto',
  processing: 'none',
  sides: 'all',
  selectedSides: [],
  customerId: '',
  conversationId: null,
  quoteId: null,
};

export const emptyReminderDraft: ReminderDraft = {
  recipientClientId: '',
  sourceAppIds: [],
  subjectType: 'interest',
  subjectRef: '',
  subjectVersion: '',
  dueAt: '',
  owner: '',
  text: '',
};

interface AppState {
  datasetId: string | null;
  quoteDrafts: Record<string, QuoteDraft>;
  reminderDrafts: Record<string, ReminderDraft>;
  activePlanIds: Record<string, string>;
  lastRunIds: Record<string, string>;
  setDataset(datasetId: string | null): void;
  updateQuoteDraft(datasetId: string, patch: Partial<QuoteDraft>): void;
  resetQuoteDraft(datasetId: string): void;
  updateReminderDraft(datasetId: string, patch: Partial<ReminderDraft>): void;
  resetReminderDraft(datasetId: string): void;
  setActivePlan(datasetId: string, planId: string): void;
  setLastRun(datasetId: string, runId: string): void;
}

function safeStorage(): Storage {
  try {
    const probe = '__glassflow_probe__';
    window.localStorage.setItem(probe, '1');
    window.localStorage.removeItem(probe);
    return window.localStorage;
  } catch {
    const memory = new Map<string, string>();
    return {
      get length() {
        return memory.size;
      },
      clear: () => memory.clear(),
      getItem: key => memory.get(key) ?? null,
      key: index => [...memory.keys()][index] ?? null,
      removeItem: key => void memory.delete(key),
      setItem: (key, value) => void memory.set(key, value),
    };
  }
}

export const useAppStore = create<AppState>()(
  persist(
    set => ({
      datasetId: null,
      quoteDrafts: {},
      reminderDrafts: {},
      activePlanIds: {},
      lastRunIds: {},
      setDataset: datasetId => set({ datasetId }),
      updateQuoteDraft: (datasetId, patch) =>
        set(state => ({
          quoteDrafts: { ...state.quoteDrafts, [datasetId]: { ...(state.quoteDrafts[datasetId] ?? emptyQuoteDraft), ...patch } },
        })),
      resetQuoteDraft: datasetId => set(state => ({ quoteDrafts: { ...state.quoteDrafts, [datasetId]: emptyQuoteDraft } })),
      updateReminderDraft: (datasetId, patch) =>
        set(state => ({
          reminderDrafts: {
            ...state.reminderDrafts,
            [datasetId]: { ...(state.reminderDrafts[datasetId] ?? emptyReminderDraft), ...patch },
          },
        })),
      resetReminderDraft: datasetId =>
        set(state => ({ reminderDrafts: { ...state.reminderDrafts, [datasetId]: emptyReminderDraft } })),
      setActivePlan: (datasetId, planId) => set(state => ({ activePlanIds: { ...state.activePlanIds, [datasetId]: planId } })),
      setLastRun: (datasetId, runId) => set(state => ({ lastRunIds: { ...state.lastRunIds, [datasetId]: runId } })),
    }),
    { name: 'glassflow-ui-v1', storage: createJSONStorage(safeStorage), version: 1 },
  ),
);

export function useQuoteDraft(datasetId: string): QuoteDraft {
  return useAppStore(state => state.quoteDrafts[datasetId] ?? emptyQuoteDraft);
}

export function useReminderDraft(datasetId: string): ReminderDraft {
  return useAppStore(state => state.reminderDrafts[datasetId] ?? emptyReminderDraft);
}

/**
 * Local cutting UI state (Zustand): selection, zoom and the unsaved draft edits.
 * The draft is a list of overrides on top of a specific plan revision. It is kept in
 * localStorage so a refresh does not lose work; it never changes the active plan —
 * only an explicit save/validate/commit through the backend does.
 */
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { Placement } from '../../api/types';

export interface PlanDraft {
  planId: string;
  baseRevision: number;
  overrides: Record<string, Placement>;
  excluded: string[];
}

interface CuttingState {
  selectedRemnantId: string | null;
  selectedPartId: string | null;
  zoom: number;
  showGap: boolean;
  drafts: Record<string, PlanDraft>;
  select(remnantId: string | null, partId?: string | null): void;
  selectPart(partId: string | null): void;
  setZoom(zoom: number): void;
  toggleGap(): void;
  setOverride(key: string, planId: string, baseRevision: number, placement: Placement): void;
  toggleExcluded(key: string, planId: string, baseRevision: number, remnantId: string): void;
  discard(key: string): void;
}

export function draftKey(datasetId: string, planId: string) {
  return `${datasetId}::${planId}`;
}

function ensure(drafts: Record<string, PlanDraft>, key: string, planId: string, baseRevision: number): PlanDraft {
  const existing = drafts[key];
  if (existing && existing.baseRevision === baseRevision) return existing;
  return { planId, baseRevision, overrides: {}, excluded: [] };
}

export const useCuttingStore = create<CuttingState>()(
  persist(
    set => ({
      selectedRemnantId: null,
      selectedPartId: null,
      zoom: 1,
      showGap: false,
      drafts: {},
      select: (remnantId, partId = null) => set({ selectedRemnantId: remnantId, selectedPartId: partId }),
      selectPart: partId => set({ selectedPartId: partId }),
      setZoom: zoom => set({ zoom: Math.min(6, Math.max(0.5, Math.round(zoom * 4) / 4)) }),
      toggleGap: () => set(state => ({ showGap: !state.showGap })),
      setOverride: (key, planId, baseRevision, placement) =>
        set(state => {
          const draft = ensure(state.drafts, key, planId, baseRevision);
          return { drafts: { ...state.drafts, [key]: { ...draft, overrides: { ...draft.overrides, [placement.part_id]: placement } } } };
        }),
      toggleExcluded: (key, planId, baseRevision, remnantId) =>
        set(state => {
          const draft = ensure(state.drafts, key, planId, baseRevision);
          const excluded = draft.excluded.includes(remnantId) ? draft.excluded.filter(id => id !== remnantId) : [...draft.excluded, remnantId];
          return { drafts: { ...state.drafts, [key]: { ...draft, excluded } } };
        }),
      discard: key =>
        set(state => {
          const drafts = { ...state.drafts };
          delete drafts[key];
          return { drafts };
        }),
    }),
    {
      name: 'glassflow-cutting-v1',
      storage: createJSONStorage(() => {
        try {
          return window.localStorage;
        } catch {
          return sessionStorage;
        }
      }),
      partialize: state => ({ drafts: state.drafts, zoom: state.zoom, showGap: state.showGap }),
    },
  ),
);

/** Effective placements = plan placements with draft overrides; parts on excluded remnants become NEW. */
export function effectivePlacements(planPlacements: Placement[], draft: PlanDraft | undefined): Placement[] {
  if (!draft) return planPlacements;
  return planPlacements.map(original => {
    const placement = draft.overrides[original.part_id] ?? original;
    if (placement.remnant_id !== 'NEW' && draft.excluded.includes(placement.remnant_id)) {
      return { ...placement, remnant_id: 'NEW', x_mm: null, y_mm: null, rot: null, lock_kind: 'none' };
    }
    return placement;
  });
}

export function draftChanged(draft: PlanDraft | undefined): boolean {
  return Boolean(draft && (Object.keys(draft.overrides).length > 0 || draft.excluded.length > 0));
}

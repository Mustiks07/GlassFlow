import { useQuery } from '@tanstack/react-query';
import { useApi } from '../../api/context';
import type { Dataset } from '../../api/types';
import { useAppStore } from '../../state/store';

export const MODE_LABEL: Record<Dataset['mode'], string> = {
  source: 'Исходный снимок · только чтение',
  workspace: 'Рабочая копия',
  contest: 'Конкурсный прогон · только чтение',
};

export const MODE_SHORT: Record<Dataset['mode'], string> = {
  source: 'Исходный',
  workspace: 'Рабочая копия',
  contest: 'Конкурс',
};

export function isMutable(dataset: Dataset | undefined | null): boolean {
  return dataset?.mode === 'workspace';
}

/** KB version used for catalog/quote calls. Prefers explicit Dataset.kb_version (requested). */
export function kbVersionOf(dataset: Dataset | undefined | null): string | null {
  if (!dataset) return null;
  if (dataset.kb_version) return dataset.kb_version;
  const entry = Object.entries(dataset.source_hashes).find(([key]) => /kb|knowledge/i.test(key));
  return entry ? `sha256:${entry[1]}` : null;
}

export function useDatasets() {
  const { api } = useApi();
  return useQuery({ queryKey: ['datasets'], queryFn: ({ signal }) => api.listDatasets(signal), staleTime: 15_000 });
}

/** Current dataset, validated against the server list. Every domain query keys on dataset_id. */
export function useCurrentDataset() {
  const datasetId = useAppStore(state => state.datasetId);
  const datasets = useDatasets();
  const dataset = datasets.data?.find(item => item.dataset_id === datasetId) ?? null;
  return { datasetId: dataset ? datasetId : null, dataset, datasets, missing: Boolean(datasetId && datasets.isSuccess && !dataset) };
}

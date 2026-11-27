import { useQuery } from '@tanstack/react-query';
import { useApi } from '../../api/context';
import type { RankedApplication, Ranking } from '../../api/types';

export function useRanking(datasetId: string, policy: 'reference' | 'validated_model' = 'reference') {
  const { api } = useApi();
  return useQuery({
    queryKey: ['ranking', datasetId, policy],
    queryFn: () => api.rank({ dataset_id: datasetId, policy }),
    staleTime: 60_000,
  });
}

export interface ClientGroup {
  client_id: string;
  apps: RankedApplication[];
  /** Position of the client's best row in the server ranking (1-based). */
  best_rank: number;
}

/**
 * Groups the 25 ranked rows by client for the working queue. Uses the server's
 * grouped_clients when provided; the order is the server's order — the UI does not
 * re-rank anything.
 */
export function groupByClient(ranking: Ranking): ClientGroup[] {
  const order = new Map<string, ClientGroup>();
  ranking.rows.forEach((row, index) => {
    const group = order.get(row.client_id);
    if (group) group.apps.push(row);
    else order.set(row.client_id, { client_id: row.client_id, apps: [row], best_rank: index + 1 });
  });
  if (ranking.grouped_clients) {
    for (const [clientId, appIds] of Object.entries(ranking.grouped_clients)) {
      const group = order.get(clientId);
      if (group && appIds.length !== group.apps.length) {
        // Server grouping is authoritative; keep rows we have, note the difference via length.
        group.apps = group.apps.filter(app => appIds.includes(app.app_id));
      }
    }
  }
  return [...order.values()];
}

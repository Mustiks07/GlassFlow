import { useQuery } from '@tanstack/react-query';
import { useApi } from '../../api/context';
import type { Job } from '../../api/types';

export const TERMINAL: Job['state'][] = ['completed', 'failed', 'cancelled', 'interrupted'];

export const JOB_STATE_LABEL: Record<Job['state'], string> = {
  queued: 'В очереди',
  running: 'Выполняется',
  completed: 'Завершено',
  failed: 'Ошибка',
  cancelled: 'Остановлено',
  interrupted: 'Прервано (перезапуск)',
};

/**
 * Bounded polling (spec §22: about once per second). Polling stops on a terminal
 * state and backs off to 3 s after two minutes so a long job never floods the API.
 */
export function useJob(jobId: string | null) {
  const { api } = useApi();
  return useQuery({
    queryKey: ['job', jobId],
    enabled: Boolean(jobId),
    queryFn: ({ signal }) => api.getJob(jobId as string, signal),
    refetchInterval: query => {
      const data = query.state.data;
      if (data && TERMINAL.includes(data.state)) return false;
      if (query.state.fetchFailureCount >= 5) return false;
      const age = Date.now() - (query.state.dataUpdatedAt || Date.now());
      return query.state.dataUpdateCount > 120 || age > 120_000 ? 3_000 : 1_000;
    },
    retry: 2,
  });
}

export function jobCancelLabel(job: Job): string | null {
  // `stopped` alone also marks a normally finished worker; only a requested cancel is a cancellation.
  if (job.state === 'cancelled' || (job.cancel_requested && job.stopped)) return 'Остановка подтверждена';
  if (job.cancel_requested) return 'Запрошена остановка — ждем подтверждения';
  return null;
}

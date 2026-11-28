import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Square } from 'lucide-react';
import { useApi } from '../../api/context';
import type { Job } from '../../api/types';
import { Button, Details, ErrorState, KeyValue, LoadingState, StatusBadge, type Tone } from '../../ui/kit';
import { errorAction, stageLabel } from '../../ui/human';
import { JOB_STATE_LABEL, TERMINAL, jobCancelLabel, useJob } from './useJob';

const TONE: Record<Job['state'], Tone> = {
  queued: 'pending',
  running: 'pending',
  completed: 'ok',
  failed: 'error',
  cancelled: 'warn',
  interrupted: 'warn',
};

function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'нет данных';
  const m = Math.floor(value / 60);
  const s = Math.round(value % 60);
  return m ? `${m} мин ${s} с` : `${s} с`;
}

/** Shows the real stage and counters reported by the job; never an invented percentage. */
export function JobPanel({ jobId, title = 'Задание' }: { jobId: string; title?: string }) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const job = useJob(jobId);
  const cancel = useMutation({
    mutationFn: () => api.cancelJob(jobId),
    onSuccess: data => queryClient.setQueryData(['job', jobId], data),
  });
  if (job.isLoading) return <LoadingState label="Получаем состояние задания…" />;
  if (job.isError) return <ErrorState error={job.error} onRetry={() => job.refetch()} context={title} />;
  const data = job.data as Job;
  const cancelText = jobCancelLabel(data);
  const terminal = TERMINAL.includes(data.state);
  return (
    <div className="job-panel" aria-live="polite">
      <div className="job-head">
        <strong>{title}</strong>
        <StatusBadge tone={TONE[data.state]}>{JOB_STATE_LABEL[data.state]}</StatusBadge>
        {cancelText && <StatusBadge tone={data.stopped || data.state === 'cancelled' ? 'warn' : 'pending'}>{cancelText}</StatusBadge>}
        {!terminal && !data.cancel_requested && (
          <Button variant="ghost" icon={<Square size={13} aria-hidden="true" />} onClick={() => cancel.mutate()} busy={cancel.isPending}>
            Остановить
          </Button>
        )}
      </div>
      <KeyValue
        items={[
          ['Этап', stageLabel(data.stage)],
          ['Прогресс', data.total ? `${data.completed ?? 0} из ${data.total}` : data.completed ? `${data.completed} шагов` : 'сервер не сообщает объем'],
          ['Время / бюджет', `${seconds(data.elapsed_seconds)} / ${seconds(data.budget_seconds)}`],
          ['Последний проверенный результат', data.last_valid_result_ref ? 'Сохранён' : 'пока нет'],
        ]}
      />
      {data.state === 'interrupted' && (
        <p className="muted">Задание прервано перезапуском приложения. Подтвержденные данные сохранены; запустите расчет заново.</p>
      )}
      {data.error_code && <p className="text-error">{errorAction(data.error_code)}</p>}
      <Details summary="Подробности задания для поддержки"><p>Номер задания: {data.job_id}</p><p>Этап сервера: {data.stage}</p>{data.error_code && <p>Код ошибки: {data.error_code}</p>}{data.last_valid_result_ref && <p>Сохранённый результат: {data.last_valid_result_ref}</p>}</Details>
      {cancel.error && <ErrorState error={cancel.error} />}
    </div>
  );
}

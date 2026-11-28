import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useApi } from '../../api/context';
import { newIdempotencyKey } from '../../api/client';
import type { Job, RunView } from '../../api/types';
import { Button, Details, ErrorState } from '../../ui/kit';

const MODULE: Record<string, string> = { cutting: 'Раскрой', assistant: 'Ответы на вопросы', quality: 'Проверка диалогов', crm: 'Отбор заявок' };
export function ResumePanel({ run, runId }: { run: RunView; runId: string }) {
  const { client } = useApi();
  const cache = useQueryClient();
  const [total, setTotal] = useState(180);
  const [reserve, setReserve] = useState(30);
  const [key, setKey] = useState(newIdempotencyKey);
  const datasetId = run.manifest.dataset_id;
  const renew = useMutation({ mutationFn: () => client.post(`/runs/${encodeURIComponent(runId)}/budget`, {
    dataset_id: datasetId, expected_version: run.version, total_budget_seconds: total, export_reserve_seconds: reserve,
  }, { idempotencyKey: key }), onSuccess: async () => { setKey(newIdempotencyKey()); await cache.invalidateQueries({ queryKey: ['run', runId] }); } });
  const terminal = run.jobs.filter(j => ['failed', 'interrupted', 'cancelled'].includes(j.state) && MODULE[j.kind ?? '']);
  return <Details summary="Продолжить незавершённый прогон">
    <p className="small">Принятый комплект сохраняется. Совпадающие проверенные строки могут быть использованы повторно; изменившиеся данные перепроверяются.</p>
    {run.budget && <div className="stack"><p>Если время истекло, сначала явно задайте новый бюджет. Во время выполнения заданий он не меняется.</p><div className="row wrap"><label>Новый общий бюджет, секунд<input type="number" min={10} max={7200} step={1} value={total} onChange={e => setTotal(Number(e.target.value))} /></label><label>Новый резерв на экспорт, секунд<input type="number" min={1} max={600} step={1} value={reserve} onChange={e => setReserve(Number(e.target.value))} /></label></div>
      <Button disabled={renew.isPending || run.status === 'running' || !datasetId || run.version == null || !Number.isInteger(total) || !Number.isInteger(reserve) || total <= reserve + 5} onClick={() => renew.mutate()}>Задать новый бюджет прогона</Button>{renew.error && <ErrorState error={renew.error} />}
    </div>}
    {terminal.length === 0 ? <p>Заданий для повторного запуска сейчас нет.</p> : terminal.map(job => <Retry key={job.job_id} job={job} runId={runId} datasetId={datasetId ?? ''} />)}
  </Details>;
}

function Retry({ job, runId, datasetId }: { job: Job; runId: string; datasetId: string }) {
  const { client } = useApi();
  const cache = useQueryClient();
  const [key, setKey] = useState(newIdempotencyKey);
  const retry = useMutation({ mutationFn: () => client.post<Job>(`/jobs/${encodeURIComponent(job.job_id)}/retry`, {}, { query: { dataset_id: datasetId }, idempotencyKey: key }),
    onSuccess: async () => { setKey(newIdempotencyKey()); await cache.invalidateQueries({ queryKey: ['run', runId] }); } });
  return <div className="stack"><Button disabled={retry.isPending || !datasetId || retry.isSuccess} onClick={() => retry.mutate()}>Повторить: {MODULE[job.kind ?? ''] ?? 'задание'}</Button>{retry.isSuccess && <p role="status">Новая попытка поставлена в очередь.</p>}{retry.error && <ErrorState error={retry.error} />}</div>;
}

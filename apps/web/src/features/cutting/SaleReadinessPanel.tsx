import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import { newIdempotencyKey } from '../../api/client';
import type { Job } from '../../api/types';
import { useAppStore } from '../../state/store';
import { Button, Details, ErrorState } from '../../ui/kit';
import { useJob } from '../shell/useJob';
import { formatMoney, formatSignedInt } from '../../lib/format';
import { errorAction } from '../../ui/human';

type Readiness = components['schemas']['SaleReadiness'];
export function SaleReadinessPanel({ datasetId, planId, revision }: { datasetId: string; planId: string; revision: number }) {
  const { api, client } = useApi();
  const cache = useQueryClient();
  const selectPlan = useAppStore(s => s.setActivePlan);
  const registries = useQuery({ queryKey: ['buyer-registries', datasetId], queryFn: () => api.listBuyerRegistries(datasetId) });
  const version = registries.data?.at(-1)?.version;
  const start = useMutation({ mutationFn: () => client.post<Job>('/sale-readiness', { dataset_id: datasetId, plan_id: planId, revision, buyer_registry_version: version, budget_seconds: 2 }, { idempotencyKey: newIdempotencyKey() }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ['plans', datasetId] }) });
  const job = useJob(start.data?.job_id ?? null);
  const result = job.data?.state === 'completed' ? job.data.result as { sale_readiness?: Readiness } | undefined : undefined;
  const ready = result?.sale_readiness;
  async function open(id: string) { await cache.invalidateQueries({ queryKey: ['plans', datasetId] }); selectPlan(datasetId, id); }
  return <Details summary="Совместная готовность плана и пяти карточек">
    <p className="small muted">Проверяем минимум три объяснимых соответствия реальным покупателям для каждого свободного исходного куска. Предполагаемое применение не означает подтверждённый спрос.</p>
    {registries.isError && <ErrorState error={registries.error} />}{!version && <p>Для проверки импортируйте реестр покупателей с evidence в разделе продажи остатков.</p>}
    <Button disabled={!version || start.isPending || job.data?.state === 'queued' || job.data?.state === 'running'} onClick={() => start.mutate()}>Проверить текущий план и ограниченную альтернативу</Button>
    {start.error && <ErrorState error={start.error} />}{job.isError && <ErrorState error={job.error} />}{job.data?.error_code && <p className="text-error">{errorAction(job.data.error_code)} Исходный план сохранён.</p>}
    {ready && <div role="status"><p>{ready.reason_ru}</p><p>Подходящих исходных кусков всего: {ready.eligible_original_ids.length}; свободных в исходном плане: {ready.baseline_free_eligible_ids.length}. Поиск: {ready.search_performed ? 'выполнен' : 'не требовался'}.</p>
      {[ready.alternative, ready.tradeoff].filter((p): p is NonNullable<typeof p> => Boolean(p)).map(p => <div key={p.plan_id} className="stack"><strong>{ready.tradeoff?.plan_id === p.plan_id ? 'Отдельный вариант с уступкой площади' : 'Проверенная альтернатива без потери площади'}</strong><p>Изменение площади: {formatSignedInt(p.metrics.covered_area_mm2 - ready.baseline.metrics.covered_area_mm2)} мм²; стоимость использованного материала: {formatMoney(ready.baseline.metrics.replacement_value_tg)} → {formatMoney(p.metrics.replacement_value_tg)}; полностью покрытые заказы: {ready.baseline.metrics.fully_covered_orders} → {p.metrics.fully_covered_orders}.</p><Button onClick={() => open(p.plan_id)}>Открыть вариант для просмотра и явного подтверждения</Button></div>)}
      <p className="small muted">Изменение действующего плана и резервов требует отдельного подтверждения. Исходный вариант, ревизия {ready.baseline.revision}, сохранён.</p>
    </div>}
  </Details>;
}

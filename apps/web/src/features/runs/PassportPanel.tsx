import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import { Details, ErrorState } from '../../ui/kit';

type Passport = components['schemas']['ResultPassport'];
export function PassportPanel({ datasetId, runId }: { datasetId: string; runId: string }) {
  const { client } = useApi();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<'current' | 'accepted'>('current');
  const query = useQuery({ queryKey: ['passport', datasetId, runId, view], enabled: open,
    queryFn: () => client.get<Passport>(`/runs/${encodeURIComponent(runId)}/passport`, { query: { dataset_id: datasetId, view } }) });
  return <details onToggle={e => setOpen(e.currentTarget.open)}><summary>Паспорт результата и история допустимых улучшений</summary>
    <label>Версия паспорта<select value={view} onChange={e => setView(e.target.value as typeof view)}><option value="current">Текущее выполнение</option><option value="accepted">Принятый полный комплект</option></select></label>
    {query.isError && <ErrorState error={query.error} />}
    {query.data && <><p>Прогон {query.data.run_id} · {query.data.status} · экспорт {query.data.export_id ?? 'не выбран'}</p><p className="small">{query.data.caveat_ru}</p>
      {!query.data.history_available && <p>Промежуточная история для этого результата не сохранена; доступен конечный результат.</p>}
      <Details summary="Входы, SHA, конфигурация, модули, время и проверки"><pre className="pre">{JSON.stringify(query.data, null, 2)}</pre></Details></>}
  </details>;
}

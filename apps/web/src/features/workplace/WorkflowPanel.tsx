import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import type { Dataset } from '../../api/types';
import { Button, ErrorState } from '../../ui/kit';

type Queue = components['schemas']['WorkflowQueue'];
const ROLE = { manager: 'Менеджер', warehouse: 'Склад', owner: 'Владелец системы' };

export function WorkflowPanel({ dataset }: { dataset: Dataset }) {
  const { client } = useApi();
  const [open, setOpen] = useState(false);
  const queue = useQuery({ queryKey: ['workflow-queue', dataset.dataset_id], enabled: open, staleTime: 0,
    queryFn: () => client.get<Queue>('/workflow/queue', { query: { dataset_id: dataset.dataset_id } }) });
  return <details className="panel" open={open} onToggle={e => setOpen(e.currentTarget.open)}>
    <summary><strong>Незавершённые заказы и следующие действия</strong></summary>
    {open && <div className="stack">
      <p className="small">Очередь показывает текущее состояние заказов, корзин и напоминаний. Переход открывает существующее действие; сам по себе он ничего не подтверждает.</p>
      <Button onClick={() => queue.refetch()} busy={queue.isFetching}>Обновить очередь</Button>
      {queue.data?.items.length === 0 && <p role="status">Незавершённых действий не найдено.</p>}
      {queue.data && queue.data.items.length > 0 && <div className="table-scroll" role="region" aria-label="Очередь незавершённых действий" tabIndex={0}>
        <table><thead><tr><th>Заявка</th><th>Ответственная роль</th><th>Следующее действие</th></tr></thead>
          <tbody>{queue.data.items.map(item => <tr key={`${item.subject_type}:${item.subject_id}`}>
            <td>{item.summary || item.subject_id}<span className="small muted"> · версия {item.version}</span></td>
            <td>{ROLE[item.responsible_role]}</td><td><a href={item.route_hint}>{item.next_action}</a></td>
          </tr>)}</tbody></table>
      </div>}
      {queue.error != null && <ErrorState error={queue.error} />}
    </div>}
  </details>;
}

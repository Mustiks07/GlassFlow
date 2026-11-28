import { useQuery } from '@tanstack/react-query';
import { Users } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useRoute } from '../../state/router';
import { useApi } from '../../api/context';
import type { Dataset } from '../../api/types';
import { formatDateTime, formatPercent } from '../../lib/format';
import { Details, EmptyState, ErrorState, LoadingState, Metric, Panel, StatusBadge, TableWrap } from '../../ui/kit';
import { RequireDataset } from '../shell/RequireDataset';
import { REMINDER_STATE, ReminderActions, ReminderEditor, SUBJECT_LABEL } from './ReminderEditor';
import { groupByClient, useRanking } from './ranking';
import { useAppStore, useReminderDraft } from '../../state/store';

export function ClientsPage() {
  return <RequireDataset>{dataset => <Clients dataset={dataset} key={dataset.dataset_id} />}</RequireDataset>;
}

const FEATURE_FIELDS = ['прошлых_заявок', 'жалоба', 'manager', 'дней_с_последнего_контакта', 'тип_клиента', 'группа_товара', 'канал', 'день_года'];

function Clients({ dataset }: { dataset: Dataset }) {
  const [policy, setPolicy] = useState<'reference' | 'validated_model'>('reference');
  const [view, setView] = useState<'queue' | 'rows'>('queue');
  const ranking = useRanking(dataset.dataset_id, policy);
  const draft = useReminderDraft(dataset.dataset_id);
  const update = useAppStore(state => state.updateReminderDraft);
  const groups = ranking.data ? groupByClient(ranking.data) : [];
  const selected = groups.find(group => group.client_id === draft.recipientClientId) ?? null;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Клиенты</p>
          <h1>Отбор 25 заявок и рабочая очередь</h1>
          <p className="lead">picks.csv содержит ровно 25 заявок; очередь группирует их по клиентам. Метка «вернулся за 60 дней» — новое обращение, не покупка.</p>
        </div>
        <label className="inline-field">
          Политика отбора
          <select value={policy} onChange={event => setPolicy(event.target.value as typeof policy)}>
            <option value="reference">Эталонная сортировка (reference)</option>
            <option value="validated_model">Проверенная модель (если доступна)</option>
          </select>
        </label>
      </header>
      {ranking.isLoading && <LoadingState label="Ранжируем заявки…" />}
      {ranking.isError && <ErrorState error={ranking.error} onRetry={() => ranking.refetch()} context="Ранжирование" />}
      {ranking.data && (
        <>
          <div className="metrics-row">
            <Metric label="Заявок в отборе" value={ranking.data.rows.length} detail={ranking.data.rows.length === 25 ? 'ровно 25' : 'ожидалось 25'} tone={ranking.data.rows.length === 25 ? 'ok' : 'error'} />
            <Metric label="Уникальных клиентов" value={ranking.data.unique_client_count} />
            <Metric label="Политика" value={ranking.data.policy} detail={ranking.data.policy_version} />
            <Metric
              label="Precision@25 по открытым меткам"
              value={ranking.data.observed_precision === null || ranking.data.observed_precision === undefined ? 'Нет фактических данных' : formatPercent(ranking.data.observed_precision)}
              detail={ranking.data.observed_precision === null || ranking.data.observed_precision === undefined ? 'меток нет — это норма для закрытого набора' : 'только открытый набор'}
            />
          </div>
          {ranking.data.target_definition && <p className="small muted">Цель: {ranking.data.target_definition}</p>}
          <div className="segmented" role="tablist" aria-label="Представление">
            <button role="tab" aria-selected={view === 'queue'} className={view === 'queue' ? 'active' : ''} onClick={() => setView('queue')}>
              Очередь по клиентам ({groups.length})
            </button>
            <button role="tab" aria-selected={view === 'rows'} className={view === 'rows' ? 'active' : ''} onClick={() => setView('rows')}>
              25 заявок (как в picks.csv)
            </button>
          </div>
          <div className="grid-2 wide-left">
            <Panel title={view === 'queue' ? 'Рабочая очередь' : 'Конкурсный результат'}>
              {view === 'rows' ? (
                <TableWrap label="25 выбранных заявок" maxHeight={560}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th scope="col" className="num">
                          №
                        </th>
                        <th scope="col">app_id</th>
                        <th scope="col">client_id</th>
                        <th scope="col" className="num">
                          {policy === 'validated_model' ? 'Оценка модели' : 'Ключ приоритета'}
                        </th>
                        <th scope="col">Почему в отборе</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ranking.data.rows.map((row, index) => (
                        <tr key={row.app_id}>
                          <td className="num">{index + 1}</td>
                          <td className="mono">{row.app_id}</td>
                          <td className="mono">{row.client_id}</td>
                          <td className="num">{row.priority.toFixed(3)}</td>
                          <td className="small">{row.reasons.join('; ')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              ) : groups.length === 0 ? (
                <EmptyState title="Очередь пуста" />
              ) : (
                <ul className="client-picks scroll" aria-label="Клиенты очереди">
                  {groups.map(group => (
                    <li key={group.client_id}>
                      <label className={`candidate${selected?.client_id === group.client_id ? ' selected' : ''}`}>
                        <input
                          type="radio"
                          name="queue-client"
                          checked={selected?.client_id === group.client_id}
                          onChange={() => update(dataset.dataset_id, { recipientClientId: group.client_id, sourceAppIds: group.apps.map(app => app.app_id) })}
                        />
                        <span>
                          <strong className="mono">{group.client_id}</strong> · лучшее место {group.best_rank} · {group.apps.length}{' '}
                          {group.apps.length === 1 ? 'заявка' : 'заявки'}: <span className="mono">{group.apps.map(app => app.app_id).join(', ')}</span>
                          <br />
                          <span className="small muted">{group.apps[0].reasons.join('; ')}</span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <div className="stack sticky-col">
              {selected ? (
                <>
                  <ClientHistory dataset={dataset} clientId={selected.client_id} />
                  <Panel title={`Напоминание для ${selected.client_id}`} subtitle="Локальная задача без внешней отправки.">
                    <ReminderEditor dataset={dataset} candidateApps={selected.apps.map(app => app.app_id)} />
                  </Panel>
                </>
              ) : (
                <Panel title="Клиент">
                  <EmptyState title="Выберите клиента в очереди">Появятся исходные заявки, признаки и форма напоминания.</EmptyState>
                </Panel>
              )}
            </div>
          </div>
        </>
      )}
      <RemindersList dataset={dataset} />
    </div>
  );
}

function ClientHistory({ dataset, clientId }: { dataset: Dataset; clientId: string }) {
  const { api } = useApi();
  const rows = useQuery({
    queryKey: ['applications', dataset.dataset_id, clientId],
    queryFn: ({ signal }) => api.applications(dataset.dataset_id, { client_id: clientId, limit: 200 }, signal),
  });
  return (
    <Panel title={`Исходные заявки ${clientId}`} subtitle="Происхождение признаков: неизмененные строки импорта (source_row).">
      {rows.isLoading && <LoadingState />}
      {rows.isError && <ErrorState error={rows.error} onRetry={() => rows.refetch()} />}
      {rows.data && (
        <TableWrap label="Заявки клиента" maxHeight={260}>
          <table className="table compact">
            <thead>
              <tr>
                <th scope="col">app_id</th>
                <th scope="col">строка</th>
                {FEATURE_FIELDS.map(field => (
                  <th scope="col" key={field}>
                    {field}
                  </th>
                ))}
                <th scope="col">фактическая метка</th>
              </tr>
            </thead>
            <tbody>
              {rows.data.rows.map(row => (
                <tr key={row.app_id}>
                  <td className="mono">{row.app_id}</td>
                  <td className="num">{row.source_row}</td>
                  {FEATURE_FIELDS.map(field => (
                    <td key={field}>{row[field] === null || row[field] === undefined || row[field] === '' ? <em className="muted">нет</em> : String(row[field])}</td>
                  ))}
                  <td>{row['вернулся_за_60_дней'] === undefined || row['вернулся_за_60_дней'] === null || row['вернулся_за_60_дней'] === '' ? <em className="muted">нет метки</em> : String(row['вернулся_за_60_дней'])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      <p className="small muted">Фактическая метка показана отдельно от оценки и не используется интерфейсом для приоритета.</p>
    </Panel>
  );
}

function RemindersList({ dataset }: { dataset: Dataset }) {
  const { api } = useApi();
  const target = useRoute().params.get('reminder_id');
  const reminders = useQuery({ queryKey: ['reminders', dataset.dataset_id], queryFn: ({ signal }) => api.listReminders(dataset.dataset_id, signal), staleTime: 0 });
  useEffect(() => {
    if (target && reminders.data) document.getElementById(`reminder-${target}`)?.scrollIntoView({ block: 'center' });
  }, [target, reminders.data]);
  return (
    <Panel title="Локальные напоминания" subtitle="Актуальность предмета перепроверяется при открытии списка и при подтверждении." actions={<Users size={16} aria-hidden="true" />}>
      {reminders.isLoading && <LoadingState />}
      {reminders.isError && <ErrorState error={reminders.error} onRetry={() => reminders.refetch()} context="Напоминания" />}
      {reminders.data && reminders.data.length === 0 && <EmptyState title="Задач пока нет" />}
      {reminders.data && reminders.data.length > 0 && (
        <TableWrap label="Напоминания">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Задача</th>
                <th scope="col">Адресат</th>
                <th scope="col">Предмет</th>
                <th scope="col">Срок</th>
                <th scope="col">Ответственный</th>
                <th scope="col">Состояние</th>
                <th scope="col">Действия</th>
              </tr>
            </thead>
            <tbody>
              {reminders.data.map(item => (
                <tr key={item.reminder_id} id={`reminder-${item.reminder_id}`} aria-selected={target === item.reminder_id}>
                  <td className="mono small">
                    {item.reminder_id}
                    <div className="muted">v{item.version}</div>
                  </td>
                  <td className="mono">{item.recipient_client_id}</td>
                  <td>
                    {SUBJECT_LABEL[item.subject_type]}
                    {item.subject_ref && <div className="mono small">{item.subject_ref}</div>}
                    <Details summary={`Основание: ${item.source_app_ids.length} заявок`}>
                      <span className="mono small">{item.source_app_ids.join(', ')}</span>
                      {item.text && <p className="small">{item.text}</p>}
                    </Details>
                  </td>
                  <td>{formatDateTime(item.due_at)}</td>
                  <td>{item.owner}</td>
                  <td>
                    <StatusBadge tone={REMINDER_STATE[item.state].tone}>{REMINDER_STATE[item.state].label}</StatusBadge>
                  </td>
                  <td>
                    <ReminderActions dataset={dataset} reminder={item} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </Panel>
  );
}

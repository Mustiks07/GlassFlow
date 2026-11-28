import { useState } from 'react';
import type { Dataset, Quote } from '../../api/types';
import { useAppStore, useReminderDraft } from '../../state/store';
import { Details, EmptyState, ErrorState, LoadingState, Panel } from '../../ui/kit';
import { ReminderEditor } from '../clients/ReminderEditor';
import { groupByClient, useRanking } from '../clients/ranking';
import { href } from '../../state/router';

/**
 * After a calculation, suggest past clients from the server ranking. CRM data has no
 * exact sizes or material_id, so a match is a possible interest, not a proven need.
 * The manager explicitly chooses the recipient; the quote's customer is not changed.
 */
export function CrmBlock({ dataset, quote }: { dataset: Dataset; quote: Quote | null }) {
  const ranking = useRanking(dataset.dataset_id);
  const draft = useReminderDraft(dataset.dataset_id);
  const update = useAppStore(state => state.updateReminderDraft);
  const [showAll, setShowAll] = useState(false);
  const groups = ranking.data ? groupByClient(ranking.data) : [];
  const visible = showAll ? groups : groups.slice(0, 5);
  const selected = groups.find(group => group.client_id === draft.recipientClientId);

  return (
    <Panel
      title="Следующее действие: CRM"
      subtitle="Возможные адресаты по серверному приоритету. Совпадение по товарной группе — интерес, а не доказанная потребность."
      actions={
        <a className="link-btn" href={href('clients')}>
          Вся очередь
        </a>
      }
    >
      {ranking.isLoading && <LoadingState label="Получаем очередь клиентов…" />}
      {ranking.isError && <ErrorState error={ranking.error} onRetry={() => ranking.refetch()} context="CRM" />}
      {ranking.data && groups.length === 0 && <EmptyState title="Очередь пуста" />}
      {groups.length > 0 && (
        <ul className="client-picks" aria-label="Возможные адресаты">
          {visible.map(group => (
            <li key={group.client_id}>
              <label className={`candidate${draft.recipientClientId === group.client_id ? ' selected' : ''}`}>
                <input
                  type="radio"
                  name="crm-recipient"
                  checked={draft.recipientClientId === group.client_id}
                  onChange={() =>
                    update(dataset.dataset_id, {
                      recipientClientId: group.client_id,
                      sourceAppIds: group.apps.map(app => app.app_id),
                      ...(quote ? { subjectType: 'quote_example', subjectRef: quote.quote_id, subjectVersion: String(quote.revision) } : {}),
                    })
                  }
                />
                <span>
                  <strong className="mono">{group.client_id}</strong> · место {group.best_rank} · заявки {group.apps.map(app => app.app_id).join(', ')}
                  <br />
                  <span className="small muted">{group.apps[0]?.reasons.slice(0, 2).join('; ')}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      {groups.length > 5 && (
        <button className="link-btn" onClick={() => setShowAll(value => !value)}>
          {showAll ? 'Свернуть' : `Показать всех (${groups.length})`}
        </button>
      )}
      {ranking.data && (
        <Details summary="Создать локальное напоминание">
          <ReminderEditor
            dataset={dataset}
            candidateApps={selected?.apps.map(app => app.app_id) ?? []}
            customerId={quote?.customer_id ?? null}
            presetSubject={quote ? { type: 'quote_example', ref: quote.quote_id, version: quote.revision } : null}
          />
        </Details>
      )}
    </Panel>
  );
}

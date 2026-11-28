import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { useApi } from '../../api/context';
import type { Dataset, DialogVerdict } from '../../api/types';
import { formatDateTime, formatMoney } from '../../lib/format';
import { Button, Details, ErrorState, Field, Panel, StatusBadge, TableWrap } from '../../ui/kit';
import { kbVersionOf } from '../shell/dataset';
import { EvidenceList } from './EvidenceList';
import type { components } from '../../../../../packages/contracts/schema';

const VERDICT: Record<DialogVerdict['verdict'], { label: string; tone: 'ok' | 'error' | 'warn' }> = {
  OK: { label: 'Цена верна', tone: 'ok' },
  ERROR: { label: 'Цена неверна', tone: 'error' },
  NEEDS_REVIEW: { label: 'Нужна проверка: недостаточно контекста', tone: 'warn' },
};
const PRICE_MEANING: Record<string, string> = { per_m2: 'за квадратный метр', per_sheet: 'за лист', retail_unit: 'за штуку в розницу', bulk_unit: 'за штуку при оптовом количестве', total: 'сумма заказа', unspecified: 'единицу нужно уточнить' };

interface Checked {
  client: string;
  manager: string;
  verdict: DialogVerdict;
}

export function QualityPanel({ dataset }: { dataset: Dataset }) {
  const { api } = useApi();
  const kbVersion = kbVersionOf(dataset);
  const [client, setClient] = useState('');
  const [manager, setManager] = useState('');
  const [history, setHistory] = useState<Checked[]>([]);
  const check = useMutation({
    mutationFn: () =>
      api.checkDialog({
        dataset_id: dataset.dataset_id,
        id: `UI-${history.length + 1}`,
        client: client.trim(),
        manager: manager.trim(),
        kb_version: kbVersion ?? '',
      }),
    onSuccess: verdict => setHistory(current => [{ client: client.trim(), manager: manager.trim(), verdict }, ...current]),
  });
  const latest = history[0];
  return (
    <div className="grid-2">
      <Panel title="Проверка ответа менеджера" subtitle="Тот же каталог и правила расчёта цены, что у ассистента. Цена проверяется в контексте вопроса клиента.">
        <form
          className="stack"
          onSubmit={event => {
            event.preventDefault();
            if (client.trim() && manager.trim()) check.mutate();
          }}
        >
          <Field label="Вопрос клиента" required>
            {props => <textarea {...props} rows={3} value={client} onChange={event => setClient(event.target.value)} />}
          </Field>
          <Field label="Ответ менеджера" required>
            {props => <textarea {...props} rows={3} value={manager} onChange={event => setManager(event.target.value)} />}
          </Field>
          <div className="row">
            <Button type="submit" variant="primary" icon={<ShieldCheck size={14} aria-hidden="true" />} busy={check.isPending} disabled={!client.trim() || !manager.trim() || !kbVersion}>
              Проверить ответ
            </Button>
          </div>
          {check.error && <ErrorState error={check.error} onRetry={() => check.mutate()} context="Проверка диалога" />}
        </form>
      </Panel>
      <Panel title="Результат" subtitle="Неопределенность не отображается зеленым.">
        <CorrectionHistory dataset={dataset} />
        {!latest && <p className="muted small">Результат появится после проверки.</p>}
        {latest && <><VerdictCard checked={latest} /><CorrectionDraft dataset={dataset} checked={latest} key={latest.verdict.id + latest.client + latest.manager} /></>}
        {history.length > 1 && (
          <TableWrap label="История проверок" maxHeight={240}>
            <table className="table compact">
              <thead>
                <tr>
                  <th scope="col">ID</th>
                  <th scope="col">Ответ менеджера</th>
                  <th scope="col">Вердикт</th>
                  <th scope="col" className="num">
                    Корректно
                  </th>
                </tr>
              </thead>
              <tbody>
                {history.slice(1).map(item => (
                  <tr key={item.verdict.id}>
                    <td className="mono">{item.verdict.id}</td>
                    <td>{item.manager}</td>
                    <td>
                      <StatusBadge tone={VERDICT[item.verdict.verdict].tone}>{VERDICT[item.verdict.verdict].label}</StatusBadge>
                    </td>
                    <td className="num">{item.verdict.correct ? formatMoney(item.verdict.correct) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Panel>
    </div>
  );
}

function VerdictCard({ checked }: { checked: Checked }) {
  const { verdict } = checked;
  const meta = VERDICT[verdict.verdict];
  return (
    <div className="stack">
      <StatusBadge tone={meta.tone}>{meta.label}</StatusBadge>
      {verdict.verdict === 'ERROR' && (
        <p>
          Правильная цена: <strong>{verdict.correct ? formatMoney(verdict.correct) : 'сервер не вернул исправление'}</strong>
        </p>
      )}
      {verdict.reference_tg && (
        <p className="small">
          Эталон: {formatMoney(verdict.reference_tg)}
          {verdict.reference_meaning ? ` · ${PRICE_MEANING[verdict.reference_meaning] ?? 'единица требует проверки'}` : ''}
        </p>
      )}
      {verdict.mentions && verdict.mentions.length > 0 && (
        <p className="small">
          Цены в ответе: {verdict.mentions.map(item => `${formatMoney(item.amount_tg)} · ${PRICE_MEANING[item.meaning] ?? 'единица требует проверки'}`).join('; ')}
        </p>
      )}
      {verdict.explanation_ru && <p className="small">{verdict.explanation_ru}</p>}
      <div>
        <strong className="small">Основание</strong>
        <EvidenceList evidence={verdict.evidence} />
      </div>
    </div>
  );
}

function CorrectionDraft({ dataset, checked }: { dataset: Dataset; checked: Checked }) {
  const { client } = useApi();
  const cache = useQueryClient();
  const draft = useMutation({ mutationFn: () => client.post<components['schemas']['ManagerCorrectionDraft']>('/dialogs/corrections', {
    dataset_id: dataset.dataset_id, id: checked.verdict.id, kb_version: kbVersionOf(dataset) ?? '', client: checked.client, manager: checked.manager,
  }), onSuccess: () => cache.invalidateQueries({ queryKey: ['correction-drafts', dataset.dataset_id] }) });
  return <div className="stack"><Button disabled={draft.isPending} onClick={() => draft.mutate()}>Подготовить проверенный черновик исправления</Button>
    {draft.error && <ErrorState error={draft.error} />}{draft.data && <DraftView value={draft.data} kbVersion={kbVersionOf(dataset)} />}
  </div>;
}

function DraftView({ value, kbVersion }: { value: components['schemas']['ManagerCorrectionDraft']; kbVersion: string | null }) {
  const stale = value.is_current === false || (Boolean(kbVersion) && value.kb_version !== kbVersion);
  return <div role="status"><strong>{stale ? 'Прайс изменился: черновик требует новой проверки' : value.status === 'DRAFT_VERIFIED' ? 'Черновик проверен по действующей базе знаний' : value.status === 'NOT_NEEDED' ? 'Исправление не требуется' : 'Нужен разбор человеком'}</strong>
    {!stale && value.answer && <p className="pre">{value.answer}</p>}{!stale && value.applicable_price_tg != null && <p>{formatMoney(value.applicable_price_tg)} · {value.unit}</p>}
    {!stale && <EvidenceList evidence={value.evidence ?? []} />}<p className="small muted">Черновик требует проверки человеком. История диалога сохранена; автоматической отправки нет.</p>
  </div>;
}

function CorrectionHistory({ dataset }: { dataset: Dataset }) {
  const { client } = useApi();
  const [open, setOpen] = useState(false);
  const drafts = useQuery({ queryKey: ['correction-drafts', dataset.dataset_id], enabled: open,
    queryFn: () => client.get<components['schemas']['ManagerCorrectionDraft'][]>('/dialogs/corrections', { query: { dataset_id: dataset.dataset_id } }) });
  return <details onToggle={e => setOpen(e.currentTarget.open)}><summary>Сохранённые черновики исправлений</summary>
    <Button onClick={() => drafts.refetch()}>Обновить черновики</Button>{drafts.isError && <ErrorState error={drafts.error} />}{drafts.data?.length === 0 && <p>Сохранённых черновиков пока нет.</p>}
    {drafts.data?.slice().reverse().map(value => <Details key={value.draft_id} summary={`Черновик от ${formatDateTime(value.created_at)}${value.is_current === false ? ' · прайс изменился' : ''}`}><DraftView value={value} kbVersion={kbVersionOf(dataset)} /></Details>)}
  </details>;
}

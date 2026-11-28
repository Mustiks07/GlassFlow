import { useMutation } from '@tanstack/react-query';
import { ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { useApi } from '../../api/context';
import type { Dataset, DialogVerdict } from '../../api/types';
import { formatMoney } from '../../lib/format';
import { Button, ErrorState, Field, Panel, StatusBadge, TableWrap } from '../../ui/kit';
import { kbVersionOf } from '../shell/dataset';
import { EvidenceList } from './EvidenceList';
import type { components } from '../../../../../packages/contracts/schema';

const VERDICT: Record<DialogVerdict['verdict'], { label: string; tone: 'ok' | 'error' | 'warn' }> = {
  OK: { label: 'OK — цена верна', tone: 'ok' },
  ERROR: { label: 'ERROR — цена неверна', tone: 'error' },
  NEEDS_REVIEW: { label: 'Нужна проверка: недостаточно контекста', tone: 'warn' },
};

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
      <Panel title="Проверка ответа менеджера" subtitle="Тот же каталог и Pricing, что у ассистента. Цена проверяется в контексте вопроса клиента.">
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
                      <StatusBadge tone={VERDICT[item.verdict.verdict].tone}>{item.verdict.verdict}</StatusBadge>
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
          {verdict.reference_meaning ? ` (${verdict.reference_meaning})` : ''}
        </p>
      )}
      {verdict.mentions && verdict.mentions.length > 0 && (
        <p className="small">
          Цены в ответе: {verdict.mentions.map(item => `${item.raw} → ${formatMoney(item.amount_tg)} (${item.meaning})`).join('; ')}
        </p>
      )}
      {verdict.explanation_ru && <p className="small">{verdict.explanation_ru}</p>}
      {verdict.reason_code && <p className="small muted mono">{verdict.reason_code}</p>}
      <div>
        <strong className="small">Основание</strong>
        <EvidenceList evidence={verdict.evidence} />
      </div>
    </div>
  );
}

function CorrectionDraft({ dataset, checked }: { dataset: Dataset; checked: Checked }) {
  const { client } = useApi();
  const draft = useMutation({ mutationFn: () => client.post<components['schemas']['ManagerCorrectionDraft']>('/dialogs/corrections', {
    dataset_id: dataset.dataset_id, id: checked.verdict.id, kb_version: kbVersionOf(dataset) ?? '', client: checked.client, manager: checked.manager,
  }) });
  return <div className="stack"><Button disabled={draft.isPending} onClick={() => draft.mutate()}>Подготовить проверенный черновик исправления</Button>
    {draft.error && <ErrorState error={draft.error} />}{draft.data && <div role="status"><strong>{draft.data.status === 'DRAFT_VERIFIED' ? 'Черновик проверен по действующей KB' : draft.data.status === 'NOT_NEEDED' ? 'Исправление не требуется' : 'Нужен разбор человеком'}</strong>
      {draft.data.answer && <p className="pre">{draft.data.answer}</p>}{draft.data.applicable_price_tg != null && <p>{formatMoney(draft.data.applicable_price_tg)} · {draft.data.unit} · {draft.data.price_meaning}</p>}
      <p className="small">Источник: {draft.data.source_ref ?? 'нет подтверждённого основания'}</p><EvidenceList evidence={draft.data.evidence ?? []} /><p className="small muted">Черновик требует проверки человеком. История диалога сохранена; автоматической отправки нет.</p>
    </div>}
  </div>;
}

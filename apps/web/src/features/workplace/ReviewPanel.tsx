import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import { newIdempotencyKey } from '../../api/client';
import type { Dataset } from '../../api/types';
import { Button, Details, ErrorState } from '../../ui/kit';

type Item = components['schemas']['IntelligenceReviewItem'];
type Preview = components['schemas']['KnowledgeImpactPreview'];
const CATEGORY: Record<string, string> = { correct_policy: 'Правильное ограничение', missing_parameter: 'Не хватает параметра', kb_fact: 'Пробел базы знаний', provider_error: 'Сбой провайдера', verifier_reject: 'Отклонение проверкой фактов' };
export function ReviewPanel({ dataset }: { dataset: Dataset }) {
  const { client } = useApi();
  const cache = useQueryClient();
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState('');
  const [item, setItem] = useState<Item | null>(null);
  const [operator, setOperator] = useState('');
  const [note, setNote] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const rows = useQuery({ queryKey: ['intel-review', dataset.dataset_id, category], enabled: open,
    queryFn: () => client.get<Item[]>('/assistant/review-items', { query: { dataset_id: dataset.dataset_id, status: 'open', ...(category ? { category } : {}) } }) });
  async function action(mode: 'resolve' | 'preview' | 'apply') {
    if (!item) return;
    setBusy(true); setError(null);
    try {
      const path = `/assistant/review-items/${encodeURIComponent(item.item_id)}`;
      if (mode === 'resolve') {
        await client.post(`${path}/resolve`, { dataset_id: dataset.dataset_id, expected_version: item.version, resolved_by: operator, resolution_note: note });
        setItem(null); await rows.refetch();
      } else if (mode === 'preview' && file) {
        setPreview(await client.post<Preview>(`${path}/kb-preview`, { dataset_id: dataset.dataset_id, expected_kb_version: item.kb_version, proposed_content: await file.text() }));
        setConfirmed(false);
      } else if (mode === 'apply' && file && preview && confirmed) {
        const form = new FormData(); form.append('file', file); form.append('expected_version', String(preview.expected_platform_version));
        await client.request('POST', preview.apply_path.replace(/^\/api\/v1/, ''), { form, idempotencyKey: newIdempotencyKey() });
        setPreview(null); setFile(null); setConfirmed(false); await cache.invalidateQueries();
      }
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <details onToggle={e => setOpen(e.currentTarget.open)}><summary>Причины отказов и пробелы базы знаний</summary>
    <label>Тип причины<select value={category} onChange={e => setCategory(e.target.value)}><option value="">Все причины</option>{Object.entries(CATEGORY).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
    {rows.isError && <ErrorState error={rows.error} />}{rows.data?.length === 0 && <p>Открытых записей нет.</p>}
    {rows.data?.map(row => <div key={row.item_id} className="row wrap"><span>{CATEGORY[row.category]} · {row.user_text} · повторов {row.occurrences}</span><Button onClick={() => { setItem(row); setPreview(null); setFile(null); setConfirmed(false); setError(null); }}>Разобрать</Button></div>)}
    {item && <div className="stack"><strong>{CATEGORY[item.category]} · версия {item.version}</strong><p>{item.user_text}</p><Details summary="Подробности причины для поддержки"><p className="small">{item.reason_codes.join(', ')}</p></Details>
      <label>Ответственный<input value={operator} onChange={e => setOperator(e.target.value)} /></label><label>Решение<textarea value={note} onChange={e => setNote(e.target.value)} /></label><Button disabled={busy || !operator.trim() || !note.trim()} onClick={() => action('resolve')}>Записать решение</Button>
      {dataset.mode === 'workspace' ? <><label>Предлагаемая новая KB JSON<input type="file" accept=".json,application/json" onChange={e => { setFile(e.target.files?.[0] ?? null); setPreview(null); setConfirmed(false); }} /></label><Button disabled={busy || !file} onClick={() => action('preview')}>Проверить последствия без изменения KB</Button></> : <p>KB конкурсного снимка неизменна. Для правок создайте рабочую копию.</p>}
      {preview && <><div role="status"><p>{preview.no_op ? 'Файл совпадает с действующей базой знаний.' : `Изменятся товары: ${preview.changed_products.length}; правила: ${preview.changed_rules.length}; соответствия материалов: ${preview.mapping_changes.length}. Потребуют перепроверки расчёты: ${preview.affected_quotes.length}.`}</p>{preview.warnings?.map(w => <p key={w}>{w}</p>)}</div><Details summary="Подробности изменений для ответственного за базу знаний"><pre className="pre">{JSON.stringify(preview, null, 2)}</pre></Details><label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Я проверил последствия и подтверждаю новую версию базы знаний рабочей копии</label><Button disabled={busy || !confirmed || preview.no_op} onClick={() => action('apply')}>Применить проверенный файл базы знаний</Button></>}
    </div>}{error != null && <ErrorState error={error} />}
  </details>;
}

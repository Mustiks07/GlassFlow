import { useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import { Button, ErrorState } from '../../ui/kit';
import type { components } from '../../../../../packages/contracts/schema';

export function OperationalDocument({ datasetId, kind, subjectId, version }: { datasetId: string; kind: 'piece' | 'order' | 'basket'; subjectId: string; version: number }) {
  const { client } = useApi();
  const [operator, setOperator] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [url, setUrl] = useState('');
  async function create() {
    setBusy(true); setError(null); setUrl('');
    try {
      const common = { dataset_id: datasetId, expected_version: version, operator };
      const result = kind === 'piece'
        ? await client.post<components['schemas']['PieceLabel']>('/piece-labels', { ...common, remnant_id: subjectId }, { idempotencyKey: newIdempotencyKey() })
        : await client.post<components['schemas']['WarehouseDocument']>('/warehouse-documents', { ...common, subject_type: kind, subject_id: subjectId }, { idempotencyKey: newIdempotencyKey() });
      const path = 'label_id' in result ? `piece-labels/${result.label_id}` : `warehouse-documents/${result.document_id}`;
      setUrl(`/api/v1/${path}/pdf?dataset_id=${encodeURIComponent(datasetId)}`);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <details><summary>{kind === 'piece' ? 'Бирка куска' : 'Лист задания складу'} · версия {version}</summary>
    <p className="small muted">Документ сохраняет снимок этой версии. Резерв, выдача и фактический расход подтверждаются отдельно.</p>
    <label>Оператор<input value={operator} onChange={e => setOperator(e.target.value)} maxLength={128} /></label>
    <Button disabled={busy || !operator.trim()} onClick={create}>Сохранить документ</Button>
    {error != null && <ErrorState error={error} />}{url && <a href={url} target="_blank" rel="noreferrer">Открыть PDF для печати</a>}
  </details>;
}

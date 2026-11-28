import { useState } from 'react';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import { Button, ErrorState } from '../../ui/kit';
import { useCuttingStore } from './draftStore';

type Resolved = components['schemas']['PieceLabelResolved'];
export function LabelLookup({ datasetId }: { datasetId: string }) {
  const { client } = useApi();
  const select = useCuttingStore(s => s.select);
  const [text, setText] = useState('');
  const [value, setValue] = useState<Resolved | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function resolve() {
    setBusy(true); setError(null); setValue(null);
    try {
      let labelId = text.trim();
      if (labelId.startsWith('{')) {
        const parsed = JSON.parse(labelId);
        if (parsed.schema !== 'glassflow-piece-v1' || parsed.dataset_id !== datasetId || typeof parsed.label_id !== 'string') throw new Error('Бирка относится к другому набору или имеет неизвестный формат.');
        labelId = parsed.label_id;
      }
      const result = await client.get<Resolved>(`/piece-labels/${encodeURIComponent(labelId)}/resolve`, { query: { dataset_id: datasetId } });
      setValue(result); select(result.current.remnant_id);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <details><summary>Открыть кусок по старой бирке / QR</summary><form className="stack" onSubmit={e => { e.preventDefault(); void resolve(); }}><label>Содержимое QR или ID бирки<textarea rows={2} value={text} onChange={e => setText(e.target.value)} /></label><Button type="submit" disabled={!text.trim() || busy}>Открыть актуальную запись</Button></form>
    {error != null && <ErrorState error={error} />}{value && <div role="status"><strong>{value.current.remnant_id} · текущая версия {value.current.version}</strong><p>{value.current.dimensions.length_mm} × {value.current.dimensions.width_mm} мм · {value.current.location_raw || 'Место неизвестно'} · {value.current.status}</p>{value.changed && <p className="text-warn">Запись изменилась после печати версии {value.label.printed_version}. Действия требуют актуальной проверки версии.</p>}<p className="small">Бирка не разрешает резерв или списание.</p></div>}
  </details>;
}

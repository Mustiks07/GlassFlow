import { useState } from 'react';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import { Button, ErrorState } from '../../ui/kit';

type Check = components['schemas']['ReleaseCheck'];
const LABEL = { ready: 'Готово', missing: 'Не хватает', mismatch: 'Не совпадает', needs_review: 'Нужна проверка' };
export function ReleaseCheckPanel({ runId }: { runId: string }) {
  const { client } = useApi();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<Check | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function check() {
    if (!file) return; setBusy(true); setError(null);
    try { const form = new FormData(); form.append('file', file); setResult((await client.request<Check>('POST', `/runs/${runId}/release-check`, { form })).data); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <details><summary>Проверить готовность конкурсного комплекта</summary><div className="stack"><p>Выберите настоящий ZIP сдачи до 64 МБ, без Windows-сборки. Проверка читает файлы и сравнивает их с принятым результатом этого прогона.</p><label>Архив конкурсного комплекта<input type="file" accept=".zip,application/zip" onChange={e => { setFile(e.target.files?.[0] ?? null); setResult(null); }} /></label><Button busy={busy} disabled={!file} onClick={check}>Проверить файлы, числа и версии</Button>{result && <div role="status"><strong>{result.files_coherent ? 'Файлы согласованы; внешняя приёмка остаётся отдельно' : 'Комплект требует доработки'}</strong><ul>{result.items.map(item => <li key={item.name}><b>{item.name}: {LABEL[item.status]}</b> — {item.message}</li>)}</ul></div>}{error != null && <ErrorState error={error} />}</div></details>;
}

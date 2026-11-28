import { useState } from 'react';
import { useApi } from '../../api/context';
import type { components } from '../../../../../packages/contracts/schema';
import { Button, Details, ErrorState, TableWrap } from '../../ui/kit';
import { formatMoney, formatPercent } from '../../lib/format';

type View = components['schemas']['ComparableView'];
type Answer = components['schemas']['AnalyticsAnswer'];
export function ComparablePanel({ datasetId }: { datasetId: string }) {
  const { client } = useApi();
  const [dimension, setDimension] = useState<'product_group' | 'channel' | 'client_type'>('product_group');
  const [view, setView] = useState<View | null>(null);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function load(ask: boolean) {
    setBusy(true); setError(null);
    try {
      if (ask) {
        const result = await client.post<Answer>('/analytics/questions', { dataset_id: datasetId, question });
        setAnswer(result); setView(result.comparison ?? null);
      } else {
        setView(await client.post<View>('/analytics/comparable', { dataset_id: datasetId, dimensions: [dimension] })); setAnswer(null);
      }
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <Details summary="Сравнить внутри сопоставимых групп">
    <p className="small muted">Группы различаются составом заявок. Эти числа описывают данные и не устанавливают причины различий.</p>
    <div className="form-row"><label>Группировка<select value={dimension} onChange={e => setDimension(e.target.value as typeof dimension)}>
      <option value="product_group">Группа товара</option><option value="channel">Канал</option><option value="client_type">Тип клиента</option>
    </select></label><Button disabled={busy} onClick={() => load(false)}>Сравнить</Button></div>
    <form onSubmit={e => { e.preventDefault(); void load(true); }} className="form-row"><label>Вопрос по агрегатам<input value={question} onChange={e => setQuestion(e.target.value)} placeholder="Какой средний чек у M1 и M2 по каналам?" /></label><Button type="submit" disabled={busy || !question.trim()}>Посчитать</Button></form>
    {error != null && <ErrorState error={error} />}
    {answer && <p role="status">{answer.answer_ru}</p>}
    {view && <><p>{view.matched_application_count} заявок · {view.total_groups} групп</p>
      {view.groups.map((group, i) => <Details key={i} summary={`${Object.values(group.dimensions).map(v => v ?? 'Неизвестно').join(' / ')} · ${group.application_count} заявок`}>
        <TableWrap label="Менеджеры в сопоставимой группе"><table className="table compact"><thead><tr><th>Менеджер</th><th>Заявок</th><th>Ответ, мин</th><th>Конверсия</th><th>Возвраты</th><th>Чек по продажам</th></tr></thead><tbody>
          {group.managers.map(m => <tr key={m.manager}><td>{m.manager}</td><td>{m.application_count}</td><td>{m.mean_response_minutes?.toFixed(1) ?? 'Нет данных'}<small> · n={m.evidence?.mean_response_minutes?.denominator ?? 0}</small></td><td>{m.conversion.value == null ? 'Нет данных' : formatPercent(m.conversion.value)} · {m.conversion.numerator}/{m.conversion.denominator}</td><td>{m.returns.value == null ? 'Нет данных' : formatPercent(m.returns.value)} · {m.returns.numerator}/{m.returns.denominator}</td><td>{m.mean_sale_tg == null ? 'Нет продаж' : formatMoney(m.mean_sale_tg)} · n={m.evidence?.mean_sale_tg?.denominator ?? 0}</td></tr>)}
        </tbody></table></TableWrap>
        {group.warnings.length > 0 && <p className="small text-warn">Малая группа или неполные данные: {group.warnings.map(w => `${w.manager}, ${w.metric}: ${w.known_count}/${w.total_count}`).join('; ')}</p>}
      </Details>)}<p className="small muted">{view.caveat_ru}</p></>}
  </Details>;
}

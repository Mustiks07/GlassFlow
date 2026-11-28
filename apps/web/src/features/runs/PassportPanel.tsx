import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import type { components } from '../../../../../packages/contracts/schema';
import { useApi } from '../../api/context';
import { Details, ErrorState } from '../../ui/kit';
import { stageLabel } from '../../ui/human';
import { formatAreaM2, formatDateTime, formatPercent } from '../../lib/format';

type Passport = components['schemas']['ResultPassport'];
export function PassportPanel({ datasetId, runId }: { datasetId: string; runId: string }) {
  const { client } = useApi();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<'current' | 'accepted'>('current');
  const query = useQuery({ queryKey: ['passport', datasetId, runId, view], enabled: open,
    queryFn: () => client.get<Passport>(`/runs/${encodeURIComponent(runId)}/passport`, { query: { dataset_id: datasetId, view } }) });
  return <details onToggle={e => setOpen(e.currentTarget.open)}><summary>Паспорт результата и история допустимых улучшений</summary>
    <label>Версия паспорта<select value={view} onChange={e => setView(e.target.value as typeof view)}><option value="current">Текущее выполнение</option><option value="accepted">Принятый полный комплект</option></select></label>
    {query.isError && <ErrorState error={query.error} />}
    {query.data && <><p>{({ ready: 'Полный комплект проверен и сохранён', completed: 'Запрошенные модули завершены', partial: 'Готова часть результатов', blocked: 'Нужна проверка данных', running: 'Выполнение продолжается' } as Record<string, string>)[query.data.status] ?? 'Требуется проверка результата'}</p><p className="small">{query.data.caveat_ru}</p>
      {query.data.modules.map((module, index) => <div key={index} className="stack"><strong>{({ cutting: 'Раскрой', assistant: 'Ответы на вопросы', quality: 'Проверка диалогов', crm: 'Отбор клиентов', cards: 'Карточки остатков' } as Record<string, string>)[String(module.module)] ?? 'Модуль прогона'} · {stageLabel(String(module.state))}</strong>
        {typeof module.started_at === 'string' && <p>Начало: {formatDateTime(module.started_at)}{typeof module.finished_at === 'string' ? `; завершение: ${formatDateTime(module.finished_at)}` : ''}</p>}
        {typeof module.stop_reason === 'string' && <p>Причина завершения: {({ completed: 'поиск завершён', time_limit: 'достигнут лимит времени, последний проверенный вариант сохранён', cancelled: 'остановлено пользователем', bounded_sale_relocation_completed: 'ограниченная проверка альтернативы завершена' } as Record<string, string>)[module.stop_reason] ?? 'см. подробности выполнения'}.</p>}
        {module.metrics != null && typeof module.metrics === 'object' && <Metrics value={module.metrics as Record<string, unknown>} />}
        {Array.isArray(module.history) && module.history.length > 0 && <Details summary="Сохранённые этапы и улучшения"><ol>{module.history.map((e: Record<string, unknown>, i: number) => <li key={i}>{e.action === 'job.valid_incumbent' ? 'Сохранён проверенный вариант' : 'Выполнение завершено'}{typeof e.elapsed_seconds === 'number' ? ` · через ${e.elapsed_seconds.toFixed(1)} с от запуска задания` : ''}{e.metrics != null && typeof e.metrics === 'object' && <Metrics value={e.metrics as Record<string, unknown>} />}</li>)}</ol></Details>}
      </div>)}
      {!query.data.history_available && <p>Промежуточная история для этого результата не сохранена; доступен конечный результат.</p>}
      <Details summary="Технический паспорт для поддержки: версии, контрольные суммы и проверки"><pre className="pre">{JSON.stringify(query.data, null, 2)}</pre></Details></>}
  </details>;
}

function Metrics({ value }: { value: Record<string, unknown> }) {
  return <p className="small">{typeof value.coverage === 'number' && <>Покрытие {formatPercent(value.coverage)}. </>}{typeof value.covered_area_mm2 === 'number' && <>Площадь из остатков {formatAreaM2(value.covered_area_mm2)}. </>}{typeof value.fully_covered_orders === 'number' && <>Полностью закрыто заказов: {value.fully_covered_orders}. </>}</p>;
}

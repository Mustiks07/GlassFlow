import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, FileUp, FolderOpen, Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import type { Dataset, ImportPreview } from '../../api/types';
import { formatDateTime, formatInt } from '../../lib/format';
import { fieldLabel, humanText } from '../../ui/human';
import { navigate } from '../../state/router';
import { useAppStore } from '../../state/store';
import { Button, Details, EmptyState, ErrorState, Field, LoadingState, Panel, StatusBadge, TableWrap } from '../../ui/kit';
import { MODE_LABEL, useDatasets } from '../shell/dataset';
import { WorkingCopyButton } from '../shell/Shell';

const KIND_LABEL: Record<string, string> = {
  materials: 'Материалы',
  stock: 'Остатки',
  orders: 'Детали заказов',
  distinct_orders: 'Заказы',
  questions: 'Вопросы',
  dialogs: 'Диалоги',
  applications: 'Заявки CRM',
  kb: 'База знаний',
};

export function DataSection() {
  return (
    <div className="stack">
      <ImportWizard />
      <DatasetList />
    </div>
  );
}

function DatasetList() {
  const datasets = useDatasets();
  const current = useAppStore(state => state.datasetId);
  const setDataset = useAppStore(state => state.setDataset);
  return (
    <Panel title="Наборы данных" subtitle="Исходные и конкурсные снимки неизменяемы. Изменения выполняются только в рабочей копии.">
      {datasets.isLoading && <LoadingState />}
      {datasets.isError && <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />}
      {datasets.data && datasets.data.length === 0 && <EmptyState title="Наборов пока нет">Загрузите файлы выше.</EmptyState>}
      {datasets.data && datasets.data.length > 0 && (
        <TableWrap label="Наборы данных">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Название</th>
                <th scope="col">Режим</th>
                <th scope="col">Создан</th>
                <th scope="col">Строки</th>
                <th scope="col">Источники</th>
                <th scope="col">Действия</th>
              </tr>
            </thead>
            <tbody>
              {datasets.data.map(item => (
                <tr key={item.dataset_id} aria-current={item.dataset_id === current ? 'true' : undefined}>
                  <td>
                    <strong>{item.name}</strong>
                    {item.parent_id && <div className="small muted">Источник: {datasets.data.find(source => source.dataset_id === item.parent_id)?.name ?? 'название исходного набора недоступно'}</div>}
                    <Details summary="Сведения о наборе для поддержки"><p>Номер набора: {item.dataset_id}</p>{item.parent_id && <p>Номер источника: {item.parent_id}</p>}</Details>
                  </td>
                  <td>{MODE_LABEL[item.mode]}</td>
                  <td>{formatDateTime(item.created_at)}</td>
                  <td>
                    <RowCounts counts={item.row_counts} />
                  </td>
                  <td>
                    <Details summary={`${Object.keys(item.source_hashes).length} файлов`}>
                      <ul className="plain mono small">
                        {Object.entries(item.source_hashes).map(([kind, hash]) => (
                          <li key={kind}>
                            {kind}: {hash}
                          </li>
                        ))}
                      </ul>
                    </Details>
                  </td>
                  <td className="actions-cell">
                    {item.dataset_id === current ? (
                      <StatusBadge tone="ok">Выбран</StatusBadge>
                    ) : (
                      <Button onClick={() => setDataset(item.dataset_id)} icon={<FolderOpen size={14} aria-hidden="true" />}>
                        Открыть
                      </Button>
                    )}
                    {item.mode !== 'workspace' && <WorkingCopyButton dataset={item} label="Копия" />}
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

function RowCounts({ counts }: { counts: Record<string, number> }) {
  return (
    <span className="small">
      {Object.entries(counts)
        .map(([kind, count]) => `${KIND_LABEL[kind] ?? 'Другие записи'}: ${formatInt(count)}`)
        .join(' · ')}
    </span>
  );
}

type Stage = 'select' | 'preview' | 'done';

function ImportWizard() {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const setDataset = useAppStore(state => state.setDataset);
  const datasets = useDatasets();
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [name, setName] = useState('Пакет организаторов');
  const [mode, setMode] = useState<'source' | 'contest'>('source');
  const [explicitCopy, setExplicitCopy] = useState(false);
  const [commitKey, setCommitKey] = useState(newIdempotencyKey);
  const [result, setResult] = useState<{ dataset: Dataset; reused: boolean } | null>(null);
  const stage: Stage = result ? 'done' : preview ? 'preview' : 'select';

  const previewMutation = useMutation({
    mutationFn: () => api.previewImport(files),
    onSuccess: data => {
      setPreview(data);
      setCommitKey(newIdempotencyKey());
    },
  });
  const commitMutation = useMutation({
    mutationFn: () => api.commitImport(preview!.import_id, { name, mode, explicit_copy: explicitCopy }, commitKey),
    onSuccess: dataset => {
      const reused = Boolean(datasets.data?.some(item => item.dataset_id === dataset.dataset_id));
      setResult({ dataset, reused });
      queryClient.invalidateQueries({ queryKey: ['datasets'] });
    },
  });

  const reset = () => {
    setFiles([]);
    setPreview(null);
    setResult(null);
    setExplicitCopy(false);
    previewMutation.reset();
    commitMutation.reset();
    if (inputRef.current) inputRef.current.value = '';
  };

  const errors = preview?.errors ?? [];
  return (
    <Panel
      title="Импорт файлов"
      subtitle="Файлы → предпросмотр → сводка и построчные ошибки → явное подтверждение снимка. Ни одна строка не удаляется молча."
    >
      <ol className="stepper" aria-label="Шаги импорта">
        <li className={stage === 'select' ? 'current' : 'done'}>1. Выбор файлов</li>
        <li className={stage === 'preview' ? 'current' : stage === 'done' ? 'done' : ''}>2. Предпросмотр</li>
        <li className={stage === 'done' ? 'current' : ''}>3. Снимок создан</li>
      </ol>

      {stage === 'select' && (
        <div className="stack">
          <Field label="ZIP-архив или CSV/JSON файлы" hint="Материалы, остатки, детали заказов, вопросы, диалоги, заявки и база знаний. Файлы с эталонными ответами и скрипты не включаются в рабочие данные.">
            {props => (
              <input
                {...props}
                ref={inputRef}
                type="file"
                multiple
                accept=".zip,.csv,.json"
                onChange={event => setFiles(Array.from(event.target.files ?? []))}
              />
            )}
          </Field>
          {files.length > 0 && (
            <ul className="plain small">
              {files.map(file => (
                <li key={file.name}>
                  <FileUp size={12} aria-hidden="true" /> {file.name} · {formatInt(file.size)} байт
                </li>
              ))}
            </ul>
          )}
          <div className="row">
            <Button variant="primary" icon={<Upload size={14} aria-hidden="true" />} disabled={!files.length} busy={previewMutation.isPending} onClick={() => previewMutation.mutate()}>
              Проверить файлы
            </Button>
          </div>
          {previewMutation.error && <ErrorState error={previewMutation.error} onRetry={() => previewMutation.mutate()} context="Предпросмотр" />}
        </div>
      )}

      {stage === 'preview' && preview && (
        <div className="stack">
          <div className="metrics-row">
            {Object.entries(preview.row_counts).map(([kind, count]) => (
              <div key={kind} className="metric">
                <span className="metric-label">{KIND_LABEL[kind] ?? 'Другие записи'}</span>
                <strong className="metric-value">{formatInt(count)}</strong>
              </div>
            ))}
          </div>
          {preview.warnings.length > 0 && (
            <div className="state state-info">
              <div>
                <strong>Предупреждения ({preview.warnings.length})</strong>
                <ul className="plain small">
                  {preview.warnings.map((warning, index) => (
                    <li key={index}>{humanText(warning, 'Проверьте данные исходного файла перед импортом.')}<Details summary="Исходное сообщение для поддержки"><p>{warning}</p></Details></li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {errors.length > 0 ? (
            <div className="stack">
              <StatusBadge tone="error">Найдено ошибок: {errors.length}. Снимок не будет создан, пока они не исправлены.</StatusBadge>
              <TableWrap label="Построчные ошибки импорта" maxHeight={360}>
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Файл</th>
                      <th scope="col">Строка</th>
                      <th scope="col">Поле</th>
                      <th scope="col">Исходное значение</th>
                      <th scope="col">Причина</th>
                    </tr>
                  </thead>
                  <tbody>
                    {errors.map((error, index) => (
                      <tr key={index}>
                        <td>{error.file}</td>
                        <td className="num">{error.row}</td>
                        <td>{fieldLabel(error.field) === 'Поле формы' ? 'Колонка исходного файла' : fieldLabel(error.field)}</td>
                        <td>{error.raw === '' ? <em className="muted">пусто</em> : <Details summary="Посмотреть значение"><span className="mono">{error.raw}</span></Details>}</td>
                        <td>{humanText(error.reason, 'Проверьте формат и значение в этой строке исходного файла.')}<Details summary="Подробности ошибки для поддержки"><p>Колонка: {error.field}</p><p>{error.reason}</p></Details></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            </div>
          ) : (
            <StatusBadge tone="ok">Ошибок не найдено</StatusBadge>
          )}
          <div className="form-grid">
            <Field label="Название снимка" required>
              {props => <input {...props} value={name} maxLength={200} onChange={event => setName(event.target.value)} />}
            </Field>
            <Field label="Режим" hint="Конкурсный снимок используется только для конкурсного прогона и не меняется.">
              {props => (
                <select {...props} value={mode} onChange={event => setMode(event.target.value as 'source' | 'contest')}>
                  <option value="source">Исходный снимок</option>
                  <option value="contest">Конкурсный снимок</option>
                </select>
              )}
            </Field>
          </div>
          <label className="check">
            <input type="checkbox" checked={explicitCopy} onChange={event => setExplicitCopy(event.target.checked)} />
            Если такие же байты уже импортированы — явно создать отдельную копию (по умолчанию откроется существующий снимок)
          </label>
          <div className="row">
            <Button variant="ghost" onClick={reset}>
              Выбрать другие файлы
            </Button>
            <Button
              variant="primary"
              disabled={errors.length > 0 || !name.trim()}
              busy={commitMutation.isPending}
              onClick={() => commitMutation.mutate()}
              icon={<CheckCircle2 size={14} aria-hidden="true" />}
            >
              Создать снимок «{name.trim() || '…'}»
            </Button>
          </div>
          {commitMutation.error && <ErrorState error={commitMutation.error} onRetry={() => commitMutation.mutate()} context="Подтверждение импорта" />}
        </div>
      )}

      {stage === 'done' && result && (
        <div className="stack">
          <div className="state state-ok" role="status">
            <CheckCircle2 size={18} aria-hidden="true" />
            <div>
              <strong>{result.reused ? 'Такой снимок уже существует — открыт существующий' : 'Снимок создан'}</strong>
              <p>
                {result.dataset.name} · {MODE_LABEL[result.dataset.mode]}
              </p>
              {result.reused && <p className="muted">Задачи и резервы не дублируются. Чтобы получить независимую копию, повторите импорт с отметкой «явно создать копию».</p>}
            </div>
          </div>
          <Details summary="Сведения о наборе для поддержки"><p>Номер набора: {result.dataset.dataset_id}</p></Details>
          <div className="row">
            <Button
              variant="primary"
              onClick={() => {
                setDataset(result.dataset.dataset_id);
                navigate('workplace');
              }}
            >
              Открыть набор
            </Button>
            <Button variant="ghost" onClick={reset}>
              Импортировать еще
            </Button>
          </div>
        </div>
      )}
    </Panel>
  );
}

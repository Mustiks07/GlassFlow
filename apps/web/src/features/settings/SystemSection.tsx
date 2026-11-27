import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DatabaseBackup, History, Power, RotateCcw } from 'lucide-react';
import { useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import type { BackupInfo } from '../../api/types';
import { formatDateTime, formatInt } from '../../lib/format';
import { Button, ConfirmDialog, EmptyState, ErrorState, Field, LoadingState, Panel, StatusBadge, TableWrap } from '../../ui/kit';

export function SystemSection() {
  return (
    <div className="stack">
      <div className="grid-2">
        <BackupPanel />
        <ShutdownPanel />
      </div>
      <JournalPanel />
    </div>
  );
}

function BackupPanel() {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const backups = useQuery({ queryKey: ['backups'], queryFn: ({ signal }) => api.listBackups(signal) });
  const [reason, setReason] = useState('');
  const [backupKey, setBackupKey] = useState(newIdempotencyKey);
  const [restoreTarget, setRestoreTarget] = useState<BackupInfo | null>(null);
  const [restoreKey, setRestoreKey] = useState(newIdempotencyKey);
  const backup = useMutation({
    mutationFn: () => api.backup(reason.trim(), backupKey),
    onSuccess: () => {
      setReason('');
      setBackupKey(newIdempotencyKey());
      queryClient.invalidateQueries({ queryKey: ['backups'] });
    },
  });
  const restore = useMutation({
    mutationFn: (target: BackupInfo) => api.restore(target.backup_id, restoreKey),
    onSuccess: () => {
      setRestoreTarget(null);
      setRestoreKey(newIdempotencyKey());
      queryClient.invalidateQueries();
    },
  });
  return (
    <Panel title="Резервные копии" subtitle="Штатный SQLite backup при работающем приложении. Восстановление сначала проверяет целостность и сохраняет текущую базу.">
      <form
        className="row align-end"
        onSubmit={event => {
          event.preventDefault();
          backup.mutate();
        }}
      >
        <Field label="Причина копии" required>
          {props => <input {...props} value={reason} onChange={event => setReason(event.target.value)} placeholder="например: перед конкурсным прогоном" />}
        </Field>
        <Button type="submit" variant="primary" icon={<DatabaseBackup size={14} aria-hidden="true" />} disabled={!reason.trim()} busy={backup.isPending}>
          Создать копию
        </Button>
      </form>
      {backup.isSuccess && <StatusBadge tone="ok">Копия создана: {backup.data.backup_id}</StatusBadge>}
      {backup.error && <ErrorState error={backup.error} onRetry={() => backup.mutate()} context="Резервная копия" />}
      {backups.isLoading && <LoadingState />}
      {backups.isError && <ErrorState error={backups.error} onRetry={() => backups.refetch()} context="Список копий" />}
      {backups.data && backups.data.length === 0 && <EmptyState title="Копий пока нет" />}
      {backups.data && backups.data.length > 0 && (
        <TableWrap label="Резервные копии" maxHeight={260}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Копия</th>
                <th scope="col">Создана</th>
                <th scope="col">Размер</th>
                <th scope="col">Целостность</th>
                <th scope="col">Действие</th>
              </tr>
            </thead>
            <tbody>
              {backups.data.map(item => (
                <tr key={item.backup_id}>
                  <td className="mono">{item.backup_id}</td>
                  <td>{formatDateTime(item.created_at)}</td>
                  <td className="num">{item.size_bytes ? `${formatInt(item.size_bytes)} Б` : '—'}</td>
                  <td>{item.integrity ?? 'не проверена'}</td>
                  <td>
                    <Button variant="ghost" icon={<RotateCcw size={14} aria-hidden="true" />} onClick={() => setRestoreTarget(item)}>
                      Восстановить
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      <ConfirmDialog
        open={Boolean(restoreTarget)}
        onOpenChange={open => {
          if (!open) {
            setRestoreTarget(null);
            restore.reset();
          }
        }}
        title="Восстановить базу из копии"
        action="Текущая база будет сохранена отдельной копией, затем заменена выбранной после проверки схемы и целостности. Все открытые экраны перезагрузят данные."
        affected={restoreTarget ? [
          { label: 'Копия', value: <span className="mono">{restoreTarget.backup_id}</span> },
          { label: 'Создана', value: formatDateTime(restoreTarget.created_at) },
        ] : []}
        confirmLabel="Восстановить эту копию"
        danger
        onConfirm={() => restoreTarget && restore.mutate(restoreTarget)}
        busy={restore.isPending}
        error={restore.error}
      />
    </Panel>
  );
}

function ShutdownPanel() {
  const { api } = useApi();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const shutdown = useMutation({ mutationFn: () => api.shutdown(reason.trim() || 'Завершение из интерфейса') });
  return (
    <Panel title="Завершение приложения" subtitle="Корректно останавливает worker, завершает записи и закрывает базу.">
      {shutdown.isSuccess ? (
        <div className="state state-ok" role="status">
          <Power size={18} aria-hidden="true" />
          <div>
            <strong>Приложение завершает работу</strong>
            <p>Вкладку можно закрыть. Для повторного запуска откройте GlassFlow.exe.</p>
          </div>
        </div>
      ) : (
        <Button variant="danger" icon={<Power size={14} aria-hidden="true" />} onClick={() => setOpen(true)}>
          Завершить GlassFlow
        </Button>
      )}
      <ConfirmDialog
        open={open}
        onOpenChange={value => {
          setOpen(value);
          if (!value) shutdown.reset();
        }}
        title="Завершить приложение"
        action="Активные расчеты будут остановлены с сохранением последнего валидного результата; незавершенные задания получат статус interrupted."
        affected={[{ label: 'Процессы', value: 'локальный API и вычислительный worker' }]}
        confirmLabel="Завершить работу"
        danger
        onConfirm={() => shutdown.mutate()}
        busy={shutdown.isPending}
        error={shutdown.error}
      >
        <Field label="Причина (для журнала)">
          {props => <input {...props} value={reason} onChange={event => setReason(event.target.value)} />}
        </Field>
      </ConfirmDialog>
    </Panel>
  );
}

function JournalPanel() {
  const { api } = useApi();
  const journal = useQuery({ queryKey: ['journal'], queryFn: ({ signal }) => api.journal(signal) });
  return (
    <Panel
      title="Журнал запуска и заданий"
      actions={
        <Button variant="ghost" icon={<History size={14} aria-hidden="true" />} onClick={() => journal.refetch()} busy={journal.isFetching}>
          Обновить
        </Button>
      }
    >
      {journal.isLoading && <LoadingState />}
      {journal.isError && <ErrorState error={journal.error} onRetry={() => journal.refetch()} context="Журнал" />}
      {journal.data && journal.data.length === 0 && <EmptyState title="Записей нет" />}
      {journal.data && journal.data.length > 0 && (
        <TableWrap label="Журнал" maxHeight={320}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Время</th>
                <th scope="col">Уровень</th>
                <th scope="col">Событие</th>
                <th scope="col">Подробности</th>
                <th scope="col">correlation_id</th>
              </tr>
            </thead>
            <tbody>
              {journal.data.map((entry, index) => (
                <tr key={index}>
                  <td>{formatDateTime(entry.at)}</td>
                  <td>{entry.level}</td>
                  <td>{entry.event}</td>
                  <td>{entry.detail}</td>
                  <td className="mono small">{entry.correlation_id ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </Panel>
  );
}

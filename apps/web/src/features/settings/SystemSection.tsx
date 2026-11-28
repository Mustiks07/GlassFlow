import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DatabaseBackup, History, Power, RotateCcw } from 'lucide-react';
import { useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import type { BackupInfo } from '../../api/types';
import { formatDateTime, formatInt } from '../../lib/format';
import { Button, ConfirmDialog, Details, EmptyState, ErrorState, LoadingState, Panel, StatusBadge, TableWrap } from '../../ui/kit';

const JOURNAL_ACTION: Record<string, string> = {
  'dataset.working_copy': 'Создана рабочая копия набора', 'import.commit': 'Завершён импорт набора',
  'labor.create': 'Создан замер трудозатрат', 'labor.start': 'Начат замер трудозатрат',
  'labor.pause': 'Замер трудозатрат приостановлен', 'labor.resume': 'Замер трудозатрат продолжен',
  'labor.finish': 'Завершён замер трудозатрат', 'piece_label.created': 'Создана бирка куска',
  'order.create': 'Создан лист заказа', 'order.bind': 'Заказ связан с расчётом',
  'order.confirm': 'Подтверждён заказ', 'order.reserve': 'Материал зарезервирован для заказа',
  'order.warehouse-check': 'Зафиксирована проверка заказа на складе',
  'order.handover': 'Заказ передан в работу складу', 'order.material_use': 'Зафиксирован расход по заказу',
  'basket.create': 'Создана корзина', 'basket.lines': 'Сохранены позиции корзины',
  'basket.parse_submitted': 'Принята заявка на разбор позиций корзины',
  'basket.bind': 'Корзина связана с расчётами', 'basket.confirm': 'Подтверждена корзина',
  'basket.reserve': 'Материал зарезервирован для корзины',
  'basket.warehouse-check': 'Зафиксирована проверка корзины на складе',
  'basket.handover': 'Корзина передана в работу складу', 'basket.material_use': 'Зафиксирован расход по корзине',
  'material_use.confirm': 'Подтверждён фактический расход материала',
  'cut.execution_recorded': 'Записано фактическое выполнение раскроя',
  'reminder.create': 'Создано напоминание', 'reminder.confirm': 'Подтверждено напоминание',
  'job.stopped': 'Изменилось состояние фонового задания',
  'job.valid_incumbent': 'Сохранён проверенный промежуточный результат',
};
const JOURNAL_LEVEL: Record<string, string> = { info: 'Информация', warning: 'Предупреждение', warn: 'Предупреждение', error: 'Ошибка', debug: 'Диагностическая запись' };
const integrityLabel = (value?: string) => value === 'ok' ? 'Целостность подтверждена' : value ? 'Требуется проверка подробностей' : 'Не проверена';

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
  const [backupKey, setBackupKey] = useState(newIdempotencyKey);
  const [restoreTarget, setRestoreTarget] = useState<BackupInfo | null>(null);
  const [restoreKey, setRestoreKey] = useState(newIdempotencyKey);
  const backup = useMutation({
    mutationFn: () => api.backup(backupKey),
    onSuccess: () => {
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
    <Panel title="Резервные копии" subtitle="Сохраняет базу при работающем приложении. Восстановление сначала проверяет целостность и сохраняет текущую базу.">
      <div className="row">
        <Button variant="primary" icon={<DatabaseBackup size={14} aria-hidden="true" />} busy={backup.isPending} onClick={() => backup.mutate()}>
          Создать резервную копию сейчас
        </Button>
      </div>
      {backup.isSuccess && (
        <StatusBadge tone="ok">
          Копия создана · {integrityLabel(backup.data.integrity)}
        </StatusBadge>
      )}
      {backup.isSuccess && <Details summary="Сведения о копии для поддержки"><p>{backup.data.backup_id}</p><p>Проверка: {backup.data.integrity ?? 'не указана'}</p><p>Контрольная сумма: {backup.data.sha256 ?? 'не указана'}</p></Details>}
      {backup.error && <ErrorState error={backup.error} onRetry={() => backup.mutate()} context="Резервная копия" />}
      {backups.isLoading && <LoadingState />}
      {backups.isError && <ErrorState error={backups.error} onRetry={() => backups.refetch()} context="Список резервных копий" />}
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
              {backups.data.map((item, index) => (
                <tr key={item.backup_id}>
                  <td>Копия {index + 1}<Details summary="Сведения для поддержки"><p>{item.backup_id}</p><p>Контрольная сумма: {item.sha256 ?? 'не указана'}</p><p>Проверка: {item.integrity ?? 'не указана'}</p></Details></td>
                  <td>{formatDateTime(item.created_at)}</td>
                  <td className="num">{item.size_bytes ? `${formatInt(item.size_bytes)} Б` : '—'}</td>
                  <td>{integrityLabel(item.integrity)}</td>
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
          { label: 'Сведения для поддержки', value: <Details summary="Номер копии"><span className="mono">{restoreTarget.backup_id}</span></Details> },
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
  const shutdown = useMutation({ mutationFn: () => api.shutdown() });
  return (
    <Panel title="Завершение приложения" subtitle="Останавливает фоновые расчёты, завершает записи и закрывает базу.">
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
        action="Активные расчёты будут остановлены с сохранением последнего проверенного результата; незавершённые задания будут отмечены как прерванные."
        affected={[{ label: 'Что остановится', value: 'локальное приложение и фоновые расчёты' }]}
        confirmLabel="Завершить работу"
        danger
        onConfirm={() => shutdown.mutate()}
        busy={shutdown.isPending}
        error={shutdown.error}
      />
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
                <th scope="col">Участник</th>
                <th scope="col">Сведения для поддержки</th>
              </tr>
            </thead>
            <tbody>
              {journal.data.map((entry, index) => (
                <tr key={index}>
                  <td>{formatDateTime(entry.at)}</td>
                  <td>{JOURNAL_LEVEL[entry.level] ?? 'Уровень не указан'}</td>
                  <td>{JOURNAL_ACTION[entry.event] ?? 'Изменение записи'}</td>
                  <td>Не указан в журнале</td>
                  <td><Details summary="Технические подробности события"><p>Событие: {entry.event}</p><p>Уровень: {entry.level}</p><p>{entry.detail}</p><p>Номер обращения: {entry.correlation_id ?? 'не указан'}</p></Details></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </Panel>
  );
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BellPlus, CheckCircle2, XCircle } from 'lucide-react';
import { useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import { asApiError } from '../../api/errors';
import type { Dataset, Reminder } from '../../api/types';
import { formatDateTime } from '../../lib/format';
import { useAppStore, useReminderDraft, type ReminderDraft } from '../../state/store';
import { Button, ConfirmDialog, ErrorState, Field, StatusBadge, type Tone } from '../../ui/kit';

export const REMINDER_STATE: Record<Reminder['state'], { label: string; tone: Tone }> = {
  draft: { label: 'Черновик', tone: 'neutral' },
  scheduled: { label: 'Запланировано', tone: 'info' },
  due: { label: 'Срок наступил', tone: 'warn' },
  done: { label: 'Выполнено', tone: 'ok' },
  cancelled: { label: 'Отменено', tone: 'neutral' },
  stale: { label: 'Устарело', tone: 'stale' },
};

export const SUBJECT_LABEL: Record<ReminderDraft['subjectType'], string> = {
  interest: 'Уточнить интерес по товарной группе',
  quote_example: 'Предложить расчет (пример аналогичного предложения)',
  specific_remnant: 'Предложить конкретный свободный остаток',
};

const ACTIVE: Reminder['state'][] = ['draft', 'scheduled', 'due'];

/** datetime-local (Asia/Qyzylorda, UTC+05:00) → ISO with explicit offset. */
export function localToIso(value: string): string | null {
  if (!value) return null;
  return `${value.length === 16 ? `${value}:00` : value}+05:00`;
}

export function ReminderEditor({
  dataset,
  candidateApps,
  customerId,
  presetSubject,
  onCreated,
}: {
  dataset: Dataset;
  /** app_ids of the selected recipient that may be cited as the basis. */
  candidateApps: string[];
  /** Customer of the current quote (different role; never changed by this form). */
  customerId?: string | null;
  presetSubject?: { type: ReminderDraft['subjectType']; ref: string; version: number | null } | null;
  onCreated?: (reminder: Reminder) => void;
}) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const draft = useReminderDraft(dataset.dataset_id);
  const update = useAppStore(state => state.updateReminderDraft);
  const [createKey, setCreateKey] = useState(newIdempotencyKey);
  const [touched, setTouched] = useState(false);
  const patch = (value: Partial<ReminderDraft>) => update(dataset.dataset_id, value);

  const reminders = useQuery({
    queryKey: ['reminders', dataset.dataset_id],
    queryFn: ({ signal }) => api.listReminders(dataset.dataset_id, signal),
  });
  const duplicates = (reminders.data ?? []).filter(item => item.recipient_client_id === draft.recipientClientId && ACTIVE.includes(item.state));

  const errors: Partial<Record<string, string>> = {};
  if (!draft.recipientClientId.trim()) errors.recipient = 'Выберите адресата';
  if (draft.sourceAppIds.length === 0) errors.apps = 'Отметьте хотя бы одну исходную заявку — основание выбора';
  if (!draft.owner.trim()) errors.owner = 'Укажите ответственного';
  if (!draft.dueAt) errors.due = 'Срок вводит менеджер (учебный день_года не превращается в дату)';
  if (draft.subjectType !== 'interest' && !draft.subjectRef.trim()) errors.subject = 'Укажите предмет: ID расчета или остатка';
  if (draft.subjectType === 'interest' && !draft.subjectRef.trim()) errors.subject = 'Укажите товарную группу';

  const create = useMutation({
    mutationFn: () =>
      api.createReminder(
        {
          dataset_id: dataset.dataset_id,
          recipient_client_id: draft.recipientClientId.trim(),
          source_app_ids: draft.sourceAppIds,
          subject_type: draft.subjectType,
          subject_ref: draft.subjectRef.trim() || null,
          subject_version: draft.subjectVersion ? Number(draft.subjectVersion) : null,
          due_at: localToIso(draft.dueAt),
          owner: draft.owner.trim(),
          text: draft.text,
        },
        createKey,
      ),
    onSuccess: reminder => {
      queryClient.invalidateQueries({ queryKey: ['reminders', dataset.dataset_id] });
      setCreateKey(newIdempotencyKey());
      setTouched(false);
      // Keep the chosen recipient and basis so the manager sees the result in context; clear only the subject.
      patch({ subjectRef: '', subjectVersion: '', text: '' });
      onCreated?.(reminder);
    },
  });
  const show = (name: string) => (touched ? errors[name] : undefined);
  const server = (name: string) => (create.error ? asApiError(create.error).fieldMessage(name) : undefined);

  return (
    <form
      className="stack"
      onSubmit={event => {
        event.preventDefault();
        setTouched(true);
        if (Object.keys(errors).length === 0) create.mutate();
      }}
      noValidate
    >
      {customerId !== undefined && (
        <p className="role-note small">
          Заказчик текущего предложения: <b>{customerId || 'не указан'}</b>. Адресат напоминания — отдельная роль; заказчик не меняется.
        </p>
      )}
      <div className="form-grid">
        <Field label="Адресат (client_id)" required error={show('recipient') ?? server('recipient_client_id')}>
          {props => <input {...props} value={draft.recipientClientId} onChange={event => patch({ recipientClientId: event.target.value, sourceAppIds: [] })} />}
        </Field>
        <Field label="Ответственный" required error={show('owner') ?? server('owner')}>
          {props => <input {...props} value={draft.owner} onChange={event => patch({ owner: event.target.value })} placeholder="M1…M5 или имя" />}
        </Field>
      </div>
      <fieldset className="fieldset">
        <legend>Основание: исходные заявки адресата</legend>
        {candidateApps.length === 0 ? (
          <p className="small muted">Выберите клиента в очереди, чтобы отметить его заявки.</p>
        ) : (
          <div className="row wrap">
            {candidateApps.map(appId => (
              <label key={appId} className="check mono">
                <input
                  type="checkbox"
                  checked={draft.sourceAppIds.includes(appId)}
                  onChange={event =>
                    patch({ sourceAppIds: event.target.checked ? [...draft.sourceAppIds, appId] : draft.sourceAppIds.filter(item => item !== appId) })
                  }
                />
                {appId}
              </label>
            ))}
          </div>
        )}
        {show('apps') && <small className="field-error">{show('apps')}</small>}
      </fieldset>
      <div className="form-grid">
        <Field label="Тип предмета">
          {props => (
            <select
              {...props}
              value={draft.subjectType}
              onChange={event => {
                const type = event.target.value as ReminderDraft['subjectType'];
                const preset = presetSubject && presetSubject.type === type ? presetSubject : null;
                patch({ subjectType: type, subjectRef: preset?.ref ?? '', subjectVersion: preset?.version?.toString() ?? '' });
              }}
            >
              {Object.entries(SUBJECT_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field
          label={draft.subjectType === 'interest' ? 'Товарная группа' : draft.subjectType === 'quote_example' ? 'ID расчета-примера' : 'ID свободного остатка'}
          required
          hint={
            draft.subjectType === 'quote_example'
              ? 'Пример отделен от заказа адресата; цена предварительная'
              : draft.subjectType === 'specific_remnant'
                ? 'Актуальность куска проверяется при создании, открытии и подтверждении'
                : 'Без обещания конкретного куска'
          }
          error={show('subject') ?? server('subject_ref')}
        >
          {props => <input {...props} value={draft.subjectRef} onChange={event => patch({ subjectRef: event.target.value })} />}
        </Field>
        <Field label="Срок (Asia/Qyzylorda)" required error={show('due') ?? server('due_at')}>
          {props => <input {...props} type="datetime-local" value={draft.dueAt} onChange={event => patch({ dueAt: event.target.value })} />}
        </Field>
        {draft.subjectType !== 'interest' && (
          <Field label="Версия предмета" hint="Сервер сверит с актуальной версией">
            {props => <input {...props} inputMode="numeric" value={draft.subjectVersion} onChange={event => patch({ subjectVersion: event.target.value.replace(/\D/g, '') })} />}
          </Field>
        )}
      </div>
      <Field label="Короткий текст задачи">
        {props => <textarea {...props} rows={2} maxLength={4000} value={draft.text} onChange={event => patch({ text: event.target.value })} />}
      </Field>
      {duplicates.length > 0 && (
        <div className="state state-info">
          <div>
            <strong>У адресата уже есть активные задачи ({duplicates.length})</strong>
            <ul className="plain small">
              {duplicates.map(item => (
                <li key={item.reminder_id}>
                  {SUBJECT_LABEL[item.subject_type]} · {item.subject_ref ?? '—'} · {REMINDER_STATE[item.state].label} · до {formatDateTime(item.due_at)}
                </li>
              ))}
            </ul>
            <p className="small muted">Отдельное обоснованное действие разрешено. Повтор того же предмета в активном периоде вернет существующую задачу.</p>
          </div>
        </div>
      )}
      <div className="row">
        <Button type="submit" variant="primary" icon={<BellPlus size={14} aria-hidden="true" />} busy={create.isPending}>
          Создать черновик напоминания
        </Button>
        <small className="muted">Локальная задача. Сообщения клиенту не отправляются.</small>
      </div>
      {create.error && <ErrorState error={create.error} context="Создание напоминания" />}
      {create.isSuccess && <StatusBadge tone="info">Черновик создан: {create.data.reminder_id}. Подтвердите его в списке задач.</StatusBadge>}
    </form>
  );
}

/** Confirm / cancel / done actions with version checks and stale handling. */
export function ReminderActions({ dataset, reminder }: { dataset: Dataset; reminder: Reminder }) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const [action, setAction] = useState<'confirm' | 'cancel' | 'done' | null>(null);
  const [key, setKey] = useState(newIdempotencyKey);
  const mutation = useMutation({
    mutationFn: (kind: 'confirm' | 'cancel' | 'done') => {
      const body = { dataset_id: dataset.dataset_id, expected_version: reminder.version };
      if (kind === 'confirm') return api.confirmReminder(reminder.reminder_id, body, key);
      if (kind === 'cancel') return api.cancelReminder(reminder.reminder_id, body, key);
      return api.updateReminder(reminder.reminder_id, { ...body, state: 'done' }, key);
    },
    onSuccess: () => {
      setAction(null);
      setKey(newIdempotencyKey());
      queryClient.invalidateQueries({ queryKey: ['reminders', dataset.dataset_id] });
    },
    onError: () => {
      setKey(newIdempotencyKey());
      queryClient.invalidateQueries({ queryKey: ['reminders', dataset.dataset_id] });
    },
  });
  const labels = {
    confirm: { title: 'Подтвердить напоминание', button: 'Запланировать', text: 'Задача станет запланированной. Сервер повторно проверит актуальность предмета.' },
    cancel: { title: 'Отменить напоминание', button: 'Отменить задачу', text: 'Задача перейдет в состояние «Отменено».' },
    done: { title: 'Отметить выполненным', button: 'Отметить выполненным', text: 'Закрытие задачи не записывает продажу и не меняет исходную метку возврата.' },
  };
  const canConfirm = reminder.state === 'draft';
  const canClose = reminder.state === 'scheduled' || reminder.state === 'due';
  const canCancel = reminder.state !== 'done' && reminder.state !== 'cancelled';
  return (
    <div className="row wrap">
      {reminder.state === 'stale' && <span className="small text-warn">{reminder.stale_reason ?? 'Предмет изменился'} — подтверждение заблокировано</span>}
      {canConfirm && (
        <Button variant="primary" icon={<CheckCircle2 size={14} aria-hidden="true" />} onClick={() => setAction('confirm')}>
          Подтвердить
        </Button>
      )}
      {canClose && <Button onClick={() => setAction('done')}>Выполнено</Button>}
      {canCancel && (
        <Button variant="ghost" icon={<XCircle size={14} aria-hidden="true" />} onClick={() => setAction('cancel')}>
          Отменить
        </Button>
      )}
      {action && (
        <ConfirmDialog
          open
          onOpenChange={open => {
            if (!open) {
              setAction(null);
              mutation.reset();
            }
          }}
          title={labels[action].title}
          action={labels[action].text}
          affected={[
            { label: 'Задача', value: <span className="mono">{reminder.reminder_id}</span> },
            { label: 'Адресат', value: reminder.recipient_client_id },
            { label: 'Предмет', value: `${SUBJECT_LABEL[reminder.subject_type]}${reminder.subject_ref ? ` · ${reminder.subject_ref}` : ''}` },
            { label: 'Ожидаемая версия', value: String(reminder.version) },
          ]}
          confirmLabel={labels[action].button}
          onConfirm={() => mutation.mutate(action)}
          busy={mutation.isPending}
          error={mutation.error}
          danger={action === 'cancel'}
        />
      )}
    </div>
  );
}

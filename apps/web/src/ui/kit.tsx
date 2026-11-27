import * as Dialog from '@radix-ui/react-dialog';
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  Clock3,
  Info,
  Loader2,
  PlugZap,
  RefreshCw,
  WifiOff,
  X,
  XCircle,
} from 'lucide-react';
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { ERROR_TITLES, asApiError, type ApiError } from '../api/errors';

// ---------------------------------------------------------------- Buttons
type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

export function Button({
  variant = 'secondary',
  busy = false,
  icon,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; busy?: boolean; icon?: ReactNode }) {
  return (
    <button
      type="button"
      {...rest}
      className={`btn btn-${variant}${className ? ` ${className}` : ''}`}
      disabled={rest.disabled || busy}
      aria-busy={busy || undefined}
    >
      {busy ? <Loader2 className="spin" size={15} aria-hidden="true" /> : icon}
      <span>{children}</span>
    </button>
  );
}

// ---------------------------------------------------------------- Status
export type Tone = 'ok' | 'warn' | 'error' | 'info' | 'neutral' | 'stale' | 'pending';

const TONE_ICON: Record<Tone, typeof CheckCircle2> = {
  ok: CheckCircle2,
  warn: AlertTriangle,
  error: XCircle,
  info: Info,
  neutral: CircleDashed,
  stale: Clock3,
  pending: Loader2,
};

/** Status is always icon + text, never colour alone (spec §21). */
export function StatusBadge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  const Icon = TONE_ICON[tone];
  return (
    <span className={`badge badge-${tone}`} title={title}>
      <Icon size={13} aria-hidden="true" className={tone === 'pending' ? 'spin' : undefined} />
      <span>{children}</span>
    </span>
  );
}

// ---------------------------------------------------------------- Fields
export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
  required,
}: {
  label: string;
  hint?: ReactNode;
  error?: string;
  children: (props: { id: string; 'aria-invalid'?: boolean; 'aria-describedby'?: string }) => ReactNode;
  htmlFor?: string;
  required?: boolean;
}) {
  const generated = useId();
  const id = htmlFor ?? generated;
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;
  return (
    <div className={`field${error ? ' field-invalid' : ''}`}>
      <label htmlFor={id}>
        {label}
        {required && <span className="required" aria-hidden="true"> *</span>}
      </label>
      {children({ id, 'aria-invalid': error ? true : undefined, 'aria-describedby': describedBy })}
      {hint && (
        <small id={hintId} className="field-hint">
          {hint}
        </small>
      )}
      {error && (
        <small id={errorId} className="field-error" role="alert">
          <XCircle size={12} aria-hidden="true" /> {error}
        </small>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Screen states
export function LoadingState({ label = 'Загрузка…' }: { label?: string }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      <Loader2 className="spin" size={18} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state state-empty">
      <CircleDashed size={22} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        {children && <p>{children}</p>}
        {action && <div className="state-action">{action}</div>}
      </div>
    </div>
  );
}

export function StaleNotice({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="state state-stale" role="status">
      <Clock3 size={18} aria-hidden="true" />
      <div>
        <strong>Устарело</strong>
        <p>{children}</p>
        {action && <div className="state-action">{action}</div>}
      </div>
    </div>
  );
}

export function OfflineAiNotice({ detail }: { detail?: string }) {
  return (
    <div className="state state-warn" role="status">
      <WifiOff size={18} aria-hidden="true" />
      <div>
        <strong>Свободный диалог ограничен</strong>
        <p>
          AI-провайдер недоступен{detail ? `: ${detail}` : ''}. Каталог, точный расчет, подбор остатков, CRM и аналитика работают
          локально. Используйте структурированную форму расчета.
        </p>
      </div>
    </div>
  );
}

const ERROR_ICON = { offline: WifiOff, timeout: Clock3, not_implemented: PlugZap } as const;

export function ErrorState({
  error,
  onRetry,
  context,
}: {
  error: unknown;
  onRetry?: () => void;
  context?: string;
}) {
  const e: ApiError = asApiError(error);
  const Icon = ERROR_ICON[e.kind as keyof typeof ERROR_ICON] ?? AlertTriangle;
  const tone = e.kind === 'conflict' || e.kind === 'not_implemented' || e.kind === 'rate_limited' ? 'warn' : 'error';
  return (
    <div className={`state state-${tone}`} role="alert">
      <Icon size={18} aria-hidden="true" />
      <div className="state-body">
        <strong>
          {ERROR_TITLES[e.kind]}
          {context ? ` · ${context}` : ''}
        </strong>
        <p>{e.message}</p>
        {e.kind === 'not_implemented' && (
          <p className="muted">Владелец модуля еще не подключил эту операцию к серверу. Данные не подменяются демонстрационными.</p>
        )}
        {e.retryAfterSeconds !== null && <p>Повторить можно через {e.retryAfterSeconds} с.</p>}
        {e.conflictObjects.length > 0 && (
          <p>
            Затронуто: <span className="mono">{e.conflictObjects.join(', ')}</span>
          </p>
        )}
        {e.fieldErrors.length > 0 && (
          <ul className="field-error-list">
            {e.fieldErrors.map(item => (
              <li key={item.field}>
                <span className="mono">{item.name}</span>: {item.message}
                {item.raw ? ` (значение: ${item.raw})` : ''}
              </li>
            ))}
          </ul>
        )}
        <div className="state-action">
          {onRetry && (e.retryable || e.kind === 'offline' || e.kind === 'timeout' || e.kind === 'server' || e.kind === 'conflict' || e.kind === 'not_implemented') && (
            <Button onClick={onRetry} icon={<RefreshCw size={14} aria-hidden="true" />}>
              {e.kind === 'conflict' ? 'Обновить состояние' : 'Повторить'}
            </Button>
          )}
          <Details summary="Технические подробности">
            <dl className="kv compact">
              <dt>Код</dt>
              <dd className="mono">{e.code}</dd>
              <dt>HTTP</dt>
              <dd className="mono">{e.status ?? 'нет ответа'}</dd>
              <dt>correlation_id</dt>
              <dd className="mono">{e.correlationId ?? 'нет'}</dd>
            </dl>
          </Details>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Layout
export function Panel({
  title,
  subtitle,
  actions,
  children,
  id,
  className,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
  className?: string;
}) {
  const headingId = useId();
  return (
    <section className={`panel${className ? ` ${className}` : ''}`} aria-labelledby={title ? headingId : undefined} id={id}>
      {(title || actions) && (
        <header className="panel-head">
          <div>
            {title && <h2 id={headingId}>{title}</h2>}
            {subtitle && <p className="panel-sub">{subtitle}</p>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Details({ summary, children, open }: { summary: ReactNode; children: ReactNode; open?: boolean }) {
  return (
    <details className="details" open={open}>
      <summary>{summary}</summary>
      <div className="details-body">{children}</div>
    </details>
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([key, value], index) => (
        <div key={index} className="kv-row">
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Metric({ label, value, detail, tone }: { label: string; value: ReactNode; detail?: ReactNode; tone?: Tone }) {
  return (
    <div className={`metric${tone ? ` metric-${tone}` : ''}`}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
      {detail && <small className="metric-detail">{detail}</small>}
    </div>
  );
}

export function TableWrap({ children, label, maxHeight }: { children: ReactNode; label: string; maxHeight?: number }) {
  return (
    <div className="table-wrap" role="region" aria-label={label} tabIndex={0} style={maxHeight ? { maxHeight } : undefined}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------- Dialogs
/** Controlled Radix dialogs have no Trigger, so remember and restore the opener's focus ourselves. */
function useReturnFocus(open: boolean) {
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (open && document.activeElement instanceof HTMLElement && document.activeElement !== document.body) opener.current = document.activeElement;
  }, [open]);
  return (event: Event) => {
    if (opener.current && document.contains(opener.current)) {
      event.preventDefault();
      opener.current.focus();
    }
  };
}

/**
 * Confirmation dialog: names the concrete action and the affected objects (spec §21).
 * Radix provides focus trap, Escape to close and focus return.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  action,
  affected,
  children,
  confirmLabel,
  onConfirm,
  busy,
  danger,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  action: string;
  affected: { label: string; value: ReactNode }[];
  children?: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  busy?: boolean;
  danger?: boolean;
  error?: unknown;
}) {
  const restoreFocus = useReturnFocus(open);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog" aria-describedby={undefined} onCloseAutoFocus={restoreFocus}>
          <header className="dialog-head">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close asChild>
              <button className="icon-btn" aria-label="Закрыть">
                <X size={16} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>
          <p className="dialog-action">{action}</p>
          {affected.length > 0 && (
            <dl className="kv compact">
              {affected.map(item => (
                <div key={item.label} className="kv-row">
                  <dt>{item.label}</dt>
                  <dd>{item.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {children}
          {error ? <ErrorState error={error} /> : null}
          <footer className="dialog-foot">
            <Dialog.Close asChild>
              <Button variant="ghost">Отмена</Button>
            </Dialog.Close>
            <Button variant={danger ? 'danger' : 'primary'} busy={busy} onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function SideDialog({
  open,
  onOpenChange,
  title,
  children,
  wide,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const restoreFocus = useReturnFocus(open);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className={`dialog dialog-side${wide ? ' dialog-wide' : ''}`} aria-describedby={undefined} onCloseAutoFocus={restoreFocus}>
          <header className="dialog-head">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close asChild>
              <button className="icon-btn" aria-label="Закрыть">
                <X size={16} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>
          <div className="dialog-scroll">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Hint({ children }: { children: ReactNode }) {
  return (
    <p className="hint">
      <CircleHelp size={13} aria-hidden="true" /> {children}
    </p>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="mono">{children}</span>;
}

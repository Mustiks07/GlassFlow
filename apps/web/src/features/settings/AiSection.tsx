import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound, PlugZap, Save, ShieldAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useApi } from '../../api/context';
import type { AISettings } from '../../api/types';
import { asApiError } from '../../api/errors';
import { formatDateTime } from '../../lib/format';
import { Button, ErrorState, Field, KeyValue, LoadingState, Panel, StatusBadge } from '../../ui/kit';

const PROFILE_LABEL: Record<AISettings['profile'], string> = {
  local_limited: 'Только локальный режим (без сети)',
  direct: 'Прямой собственный ключ',
  judge_gateway: 'Шлюз для жюри (judge_gateway)',
};

export function AiSection() {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ['settings'], queryFn: ({ signal }) => api.getSettings(signal) });
  const [form, setForm] = useState<AISettings | null>(null);
  // The key lives only in this input's state until it is sent; it is cleared right after.
  const [apiKey, setApiKey] = useState('');
  const [paidConfirmed, setPaidConfirmed] = useState(false);

  useEffect(() => {
    if (settings.data) setForm(settings.data);
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (body: AISettings) => api.updateSettings({ ...body, api_key: apiKey || undefined }),
    onSuccess: data => {
      setApiKey('');
      setPaidConfirmed(false);
      queryClient.setQueryData(['settings'], data);
    },
    onError: () => setApiKey(''),
  });
  const check = useMutation({ mutationFn: () => api.checkAi() });

  if (settings.isLoading) return <LoadingState label="Загружаем профиль AI…" />;
  if (settings.isError) return <ErrorState error={settings.error} onRetry={() => settings.refetch()} context="Настройки AI" />;
  if (!form) return null;

  const update = (patch: Partial<AISettings>) => setForm(current => (current ? { ...current, ...patch } : current));
  const paid = form.mode === 'paid_enabled';
  const paidBlocked = paid && !settings.data?.paid_enabled && !paidConfirmed;
  const fieldError = (name: string) => (save.error ? asApiError(save.error).fieldMessage(name) : undefined);

  return (
    <div className="grid-2">
      <Panel title="Профиль AI" subtitle="По умолчанию режим без денежных списаний. Платная модель включается только явно, с бюджетом.">
        <form
          className="stack"
          onSubmit={event => {
            event.preventDefault();
            if (!paidBlocked) save.mutate(form);
          }}
        >
          {form.provider === 'basisweb' && <div className="stack"><label className="check"><input type="checkbox" checked={Boolean(form.included_quota_enabled)} onChange={e => update({ included_quota_enabled: e.target.checked })} />Разрешить расход включённой квоты BasisWeb</label><label>Лимит взвешенных токенов сессии<input type="number" min={1} max={5000000} value={form.quota_token_budget ?? 1000000} onChange={e => update({ quota_token_budget: Number(e.target.value) })} /></label><p className="small muted">Квота проверяется до запроса. Этот режим не включает денежную оплату. Новый процесс начинает отдельную сессию учёта.</p></div>}
          <div className="form-grid">
            <Field label="Профиль доступа" error={fieldError('profile')}>
              {props => (
                <select {...props} value={form.profile} onChange={event => update({ profile: event.target.value as AISettings['profile'] })}>
                  {Object.entries(PROFILE_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Провайдер" error={fieldError('provider')}>
              {props => (
                <select {...props} value={form.provider} onChange={event => update({ provider: event.target.value as AISettings['provider'] })}>
                  <option value="gemini">Gemini (основной)</option>
                  <option value="openrouter">OpenRouter (альтернативный)</option>
                  <option value="basisweb">BasisWeb (включённая квота)</option>
                </select>
              )}
            </Field>
            <Field
              label="Модель"
              hint={form.allowed_models?.length ? 'Только из проверенного профиля' : 'Введите точное название модели из инструкции выбранного сервиса'}
              error={fieldError('model_id')}
            >
              {props =>
                form.allowed_models?.length ? (
                  <select {...props} value={form.model_id} onChange={event => update({ model_id: event.target.value })}>
                    <option value="">Не выбрана</option>
                    {form.allowed_models.map(model => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input {...props} value={form.model_id} maxLength={200} onChange={event => update({ model_id: event.target.value })} />
                )
              }
            </Field>
            {form.profile === 'judge_gateway' && (
              <Field label="Адрес шлюза (HTTPS)" error={fieldError('gateway_url')}>
                {props => <input {...props} type="url" value={form.gateway_url ?? ''} onChange={event => update({ gateway_url: event.target.value || null })} />}
              </Field>
            )}
            <Field label="Тайм-аут запроса, с" error={fieldError('timeout_seconds')}>
              {props => (
                <input {...props} type="number" min={1} max={120} value={form.timeout_seconds} onChange={event => update({ timeout_seconds: Number(event.target.value) })} />
              )}
            </Field>
            <Field label="Запросов в минуту (RPM)" error={fieldError('rpm')}>
              {props => <input {...props} type="number" min={1} max={1000} value={form.rpm} onChange={event => update({ rpm: Number(event.target.value) })} />}
            </Field>
          </div>

          <Field
            label="API-ключ провайдера"
            hint={
              form.secret_present
                ? 'Ключ сохранен на сервере и не возвращается в браузер. Введите новый, чтобы заменить.'
                : 'Ключ отправляется на локальный сервер и не хранится в браузере.'
            }
            error={fieldError('api_key')}
          >
            {props => (
              <input
                {...props}
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={apiKey}
                placeholder={form.secret_present ? '•••••••• (сохранен)' : 'не задан'}
                onChange={event => setApiKey(event.target.value)}
              />
            )}
          </Field>

          <fieldset className="fieldset">
            <legend>Режим оплаты</legend>
            <label className="check">
              <input type="radio" name="ai-mode" checked={!paid} onChange={() => update({ mode: 'free_only', paid_enabled: false })} />
              Без денежных списаний. Расход включённой квоты разрешается отдельно.
            </label>
            <label className="check">
              <input type="radio" name="ai-mode" checked={paid} onChange={() => update({ mode: 'paid_enabled', paid_enabled: true })} />
              Разрешить платный профиль
            </label>
            {paid && (
              <div className="state state-warn">
                <ShieldAlert size={18} aria-hidden="true" />
                <div className="stack">
                  <strong>Платный режим тратит деньги по тарифу провайдера</strong>
                  <Field label="Месячный бюджет, ₸" hint="Десятичная строка, например 5000" error={fieldError('monthly_budget_tg')}>
                    {props => (
                      <input
                        {...props}
                        inputMode="decimal"
                        value={form.monthly_budget_tg}
                        onChange={event => update({ monthly_budget_tg: event.target.value.replace(',', '.') })}
                      />
                    )}
                  </Field>
                  {!settings.data?.paid_enabled && (
                    <label className="check">
                      <input type="checkbox" checked={paidConfirmed} onChange={event => setPaidConfirmed(event.target.checked)} />
                      Я включаю платный профиль с указанным бюджетом
                    </label>
                  )}
                </div>
              </div>
            )}
          </fieldset>

          <div className="row">
            <Button type="submit" variant="primary" icon={<Save size={14} aria-hidden="true" />} busy={save.isPending} disabled={paidBlocked}>
              Сохранить профиль
            </Button>
          </div>
          {save.isSuccess && <StatusBadge tone="ok">Профиль сохранен (версия {save.data.version})</StatusBadge>}
          {save.error && <ErrorState error={save.error} context="Сохранение профиля" />}
        </form>
      </Panel>

      <Panel title="Проверка соединения" subtitle="Реальный вызов через сервер. Без ключа локальное ядро продолжает работать.">
        <KeyValue
          items={[
            ['Профиль', PROFILE_LABEL[settings.data!.profile]],
            ['Провайдер / модель', `${settings.data!.provider} / ${settings.data!.model_id || 'не выбрана'}`],
            ['Режим', settings.data!.mode === 'free_only' ? 'Без денежных списаний' : 'Платный профиль разрешён'],
            ['Бюджет', `${settings.data!.monthly_budget_tg} ₸ в месяц`],
            ['Ключ', settings.data!.secret_present ? <StatusBadge tone="ok">сохранен на сервере</StatusBadge> : <StatusBadge tone="neutral">не задан</StatusBadge>],
            ['Повторы / параллельность', `${settings.data!.max_retries} / ${settings.data!.max_parallel}`],
          ]}
        />
        <div className="row">
          <Button icon={<PlugZap size={14} aria-hidden="true" />} onClick={() => check.mutate()} busy={check.isPending}>
            Проверить соединение
          </Button>
        </div>
        {check.data && (
          <div className={`state ${check.data.available ? 'state-ok' : 'state-warn'}`} role="status">
            <KeyRound size={18} aria-hidden="true" />
            <div>
              <strong>{check.data.available ? 'Провайдер доступен' : 'Провайдер недоступен'}</strong>
              {check.data.message_ru && <p>{check.data.message_ru}</p>}
              <p className="small">
                {check.data.provider ?? '—'} · {check.data.model_id ?? '—'}
                {check.data.checked_at && <> · проверено {formatDateTime(check.data.checked_at)}</>}
              </p>
              {check.data.capabilities && (
                <p className="small">
                  Возможности:{' '}
                  {Object.entries(check.data.capabilities)
                    .map(([name, value]) => `${name}: ${value ? 'да' : 'нет'}`)
                    .join(', ') || 'не сообщены'}
                </p>
              )}
            </div>
          </div>
        )}
        {check.error && <ErrorState error={check.error} onRetry={() => check.mutate()} context="Проверка AI" />}
      </Panel>
    </div>
  );
}

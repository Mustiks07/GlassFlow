/**
 * Uniform client-side error. Mirrors the backend envelope
 * {code, message_ru, field_errors, conflict_objects, retryable, correlation_id}
 * and adds network-level reasons so every screen can render one error component.
 */

export type ErrorKind =
  | 'validation' // 422
  | 'conflict' // 409
  | 'not_found' // 404
  | 'rate_limited' // 429
  | 'unavailable' // 503
  | 'not_implemented' // 501 — module not yet delivered by its owner
  | 'forbidden' // 403
  | 'too_large' // 413
  | 'server' // 500 and other unexpected
  | 'offline' // no response
  | 'timeout'
  | 'contract'; // response does not match the expected schema

export interface FieldError {
  /** Dotted path as reported by the backend, e.g. body.dimensions.length_mm */
  field: string;
  /** Last meaningful segment for matching a form control, e.g. length_mm */
  name: string;
  message: string;
  raw?: string;
}

export class ApiError extends Error {
  constructor(
    readonly kind: ErrorKind,
    readonly status: number | null,
    readonly code: string,
    message: string,
    readonly fieldErrors: FieldError[] = [],
    readonly conflictObjects: string[] = [],
    readonly retryable = false,
    readonly correlationId: string | null = null,
    readonly retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  fieldMessage(name: string): string | undefined {
    return this.fieldErrors.find(error => error.name === name || error.field.endsWith(`.${name}`))?.message;
  }
}

const REASONS: Record<string, string> = {
  missing: 'Обязательное поле',
  int_type: 'Нужно целое число',
  int_parsing: 'Нужно целое число',
  int_from_float: 'Нужно целое число без дробной части',
  float_type: 'Нужно число',
  greater_than: 'Значение слишком мало',
  greater_than_equal: 'Значение слишком мало',
  less_than_equal: 'Значение слишком велико',
  string_too_short: 'Поле не заполнено',
  string_too_long: 'Слишком длинное значение',
  string_pattern_mismatch: 'Неверный формат',
  literal_error: 'Недопустимое значение',
  extra_forbidden: 'Лишнее поле',
  bool_type: 'Нужно да/нет',
  value_error: 'Неверное значение',
  too_short: 'Недостаточно элементов',
  too_long: 'Слишком много элементов',
};

function hasCyrillic(text: string): boolean {
  return /[А-Яа-яЁё]/.test(text);
}

export function translateFieldError(entry: Record<string, string>): FieldError {
  const field = entry.field ?? entry.loc ?? '';
  const segments = field.split('.').filter(segment => segment && segment !== 'body' && segment !== 'query');
  const name = segments.filter(segment => !/^\d+$/.test(segment)).at(-1) ?? field;
  const reason = entry.reason ?? entry.type ?? '';
  const message = entry.message_ru ?? entry.message ?? (hasCyrillic(reason) ? reason : REASONS[reason] ?? 'Проверьте значение');
  return { field, name, message, raw: entry.raw };
}

const KIND_BY_STATUS: Record<number, ErrorKind> = {
  400: 'validation',
  403: 'forbidden',
  404: 'not_found',
  409: 'conflict',
  413: 'too_large',
  422: 'validation',
  429: 'rate_limited',
  501: 'not_implemented',
  503: 'unavailable',
};

const DEFAULT_MESSAGE: Record<ErrorKind, string> = {
  validation: 'Проверьте заполнение полей.',
  conflict: 'Данные изменились. Обновите состояние и повторите действие.',
  not_found: 'Объект не найден в выбранном наборе данных.',
  rate_limited: 'Слишком много запросов. Повторите позже.',
  unavailable: 'Зависимый сервис временно недоступен.',
  not_implemented: 'Модуль еще не подключен в этой сборке.',
  forbidden: 'Действие не разрешено для этой сессии.',
  too_large: 'Файл слишком большой.',
  server: 'Внутренняя ошибка сервера.',
  offline: 'Нет связи с локальным сервером GlassFlow.',
  timeout: 'Сервер не ответил вовремя.',
  contract: 'Ответ сервера не соответствует контракту.',
};

export function errorFromResponse(status: number, body: unknown, headers: Record<string, string>): ApiError {
  const kind = KIND_BY_STATUS[status] ?? 'server';
  const envelope = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>;
  const fieldErrors = Array.isArray(envelope.field_errors)
    ? (envelope.field_errors as Record<string, string>[]).map(translateFieldError)
    : [];
  const conflicts = Array.isArray(envelope.conflict_objects) ? (envelope.conflict_objects as unknown[]).map(String) : [];
  const message = typeof envelope.message_ru === 'string' && envelope.message_ru ? envelope.message_ru : DEFAULT_MESSAGE[kind];
  const correlation =
    (typeof envelope.correlation_id === 'string' ? envelope.correlation_id : null) ?? headers['x-correlation-id'] ?? null;
  const retryAfterRaw = headers['retry-after'];
  const retryAfter = retryAfterRaw && /^\d+$/.test(retryAfterRaw) ? Number(retryAfterRaw) : null;
  const retryable = typeof envelope.retryable === 'boolean' ? envelope.retryable : kind === 'rate_limited' || kind === 'unavailable';
  return new ApiError(
    kind,
    status,
    typeof envelope.code === 'string' ? envelope.code : `HTTP_${status}`,
    message,
    fieldErrors,
    conflicts,
    retryable,
    correlation,
    retryAfter,
  );
}

export function networkError(reason: 'offline' | 'timeout'): ApiError {
  return new ApiError(reason, null, reason === 'offline' ? 'NETWORK_OFFLINE' : 'NETWORK_TIMEOUT', DEFAULT_MESSAGE[reason], [], [], true);
}

export function contractError(detail: string): ApiError {
  return new ApiError('contract', null, 'CONTRACT_MISMATCH', `${DEFAULT_MESSAGE.contract} ${detail}`);
}

export function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError('server', null, 'CLIENT_ERROR', error instanceof Error ? error.message : 'Неизвестная ошибка');
}

export const ERROR_TITLES: Record<ErrorKind, string> = {
  validation: 'Ошибка в данных',
  conflict: 'Конфликт версий',
  not_found: 'Не найдено',
  rate_limited: 'Лимит запросов',
  unavailable: 'Сервис недоступен',
  not_implemented: 'Модуль не подключен',
  forbidden: 'Нет доступа',
  too_large: 'Слишком большой файл',
  server: 'Ошибка сервера',
  offline: 'Нет связи',
  timeout: 'Превышено время ожидания',
  contract: 'Несовместимый ответ',
};

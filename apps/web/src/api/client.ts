import { ApiError, contractError, errorFromResponse, networkError } from './errors';
import { TransportFailure, type HttpMethod, type Transport, type TransportRequest } from './transport';

export interface RequestOptions {
  query?: TransportRequest['query'];
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  /** Required for confirm/commit/consume/export style mutations. */
  idempotencyKey?: string;
  timeoutMs?: number;
  /** Optional structural check of the response; throws contract error if it fails. */
  validate?: (value: unknown) => boolean;
}

export interface ApiResult<T> {
  data: T;
  correlationId: string | null;
  headers: Record<string, string>;
}

const MUTATING = new Set<HttpMethod>(['POST', 'PATCH', 'PUT', 'DELETE']);
const DEFAULT_TIMEOUT_MS = 30_000;

export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `idem-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function newRequestId(): string {
  return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * The single API client used by every screen.
 * - keeps the local session token in memory only (never localStorage);
 * - attaches X-GlassFlow-Session to mutating requests;
 * - attaches Idempotency-Key when the caller supplies one (callers keep the key
 *   for the lifetime of a user action so a retry after an error reuses it);
 * - converts every failure into ApiError with Russian text and correlation id.
 */
export class ApiClient {
  private sessionToken: string | null = null;
  private sessionPromise: Promise<string | null> | null = null;

  constructor(readonly transport: Transport) {}

  get transportKind() {
    return this.transport.kind;
  }

  /** Fetches /session. Missing endpoint (404/501) is tolerated: cookie-based session still works. */
  async ensureSession(force = false): Promise<string | null> {
    if (this.sessionToken && !force) return this.sessionToken;
    if (!this.sessionPromise || force) {
      this.sessionPromise = this.transport
        .request({ method: 'GET', path: '/session', headers: { 'X-Request-ID': newRequestId() }, timeoutMs: 10_000 })
        .then(response => {
          const body = response.body as { session_token?: unknown } | null;
          this.sessionToken = response.status === 200 && body && typeof body.session_token === 'string' ? body.session_token : null;
          return this.sessionToken;
        })
        .catch(() => null)
        .finally(() => {
          this.sessionPromise = null;
        });
    }
    return this.sessionPromise;
  }

  async request<T>(method: HttpMethod, path: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
    const attempt = async (retrySession: boolean): Promise<ApiResult<T>> => {
      const headers: Record<string, string> = { 'X-Request-ID': newRequestId() };
      if (MUTATING.has(method)) {
        const token = await this.ensureSession();
        if (token) headers['X-GlassFlow-Session'] = token;
      }
      if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;
      let response;
      try {
        response = await this.transport.request({
          method,
          path,
          query: options.query,
          body: options.body,
          form: options.form,
          headers,
          signal: options.signal,
          timeoutMs: options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
        });
      } catch (error) {
        if (error instanceof TransportFailure) {
          if (error.reason === 'aborted') throw error;
          throw networkError(error.reason);
        }
        throw networkError('offline');
      }
      if (response.status === 403 && retrySession && MUTATING.has(method)) {
        const code = (response.body as { code?: string } | null)?.code;
        if (code === 'LOCAL_SESSION_REQUIRED' || code === 'OWNER_TOKEN_REQUIRED') {
          // The request was rejected before execution; refreshing the token and retrying once is safe.
          await this.ensureSession(true);
          return attempt(false);
        }
      }
      if (response.status < 200 || response.status >= 300) {
        throw errorFromResponse(response.status, response.body, response.headers);
      }
      if (options.validate && !options.validate(response.body)) {
        throw contractError(`${method} ${path}`);
      }
      return { data: response.body as T, correlationId: response.headers['x-correlation-id'] ?? null, headers: response.headers };
    };
    return attempt(true);
  }

  async get<T>(path: string, options?: RequestOptions) {
    return (await this.request<T>('GET', path, options)).data;
  }
  async post<T>(path: string, body?: unknown, options?: RequestOptions) {
    return (await this.request<T>('POST', path, { ...options, body })).data;
  }
  async patch<T>(path: string, body?: unknown, options?: RequestOptions) {
    return (await this.request<T>('PATCH', path, { ...options, body })).data;
  }
}

export { ApiError };

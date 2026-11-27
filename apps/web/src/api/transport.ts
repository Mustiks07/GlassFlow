/**
 * Transport seam between the typed API client and the actual carrier.
 *
 * Production uses `httpTransport` (fetch to the local FastAPI under /api/v1).
 * The fixture transport lives in ./fixtures and is selected ONLY by an explicit
 * build/test flag (see ./config.ts). There is no automatic fallback from HTTP to
 * fixtures on network errors: a failed request is shown as a failed request.
 */

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

export interface TransportRequest {
  method: HttpMethod;
  /** Path relative to /api/v1, starting with '/'. */
  path: string;
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  form?: FormData;
  headers: Record<string, string>;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface TransportResponse {
  status: number;
  headers: Record<string, string>;
  /** Parsed JSON body, raw text, or a Blob for file downloads. */
  body: unknown;
}

export interface Transport {
  readonly kind: 'http' | 'fixture';
  request(request: TransportRequest): Promise<TransportResponse>;
}

/** Network-level failure (no HTTP response at all). */
export class TransportFailure extends Error {
  constructor(message: string, readonly reason: 'offline' | 'timeout' | 'aborted') {
    super(message);
    this.name = 'TransportFailure';
  }
}

export function buildQuery(query: TransportRequest['query']): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : '';
}

export const API_PREFIX = '/api/v1';

export const httpTransport: Transport = {
  kind: 'http',
  async request(request) {
    const controller = new AbortController();
    const onAbort = () => controller.abort();
    request.signal?.addEventListener('abort', onAbort, { once: true });
    let timedOut = false;
    const timer = request.timeoutMs
      ? setTimeout(() => {
          timedOut = true;
          controller.abort();
        }, request.timeoutMs)
      : undefined;
    const headers: Record<string, string> = { Accept: 'application/json', ...request.headers };
    let body: BodyInit | undefined;
    if (request.form) body = request.form;
    else if (request.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(request.body);
    }
    try {
      const response = await fetch(`${API_PREFIX}${request.path}${buildQuery(request.query)}`, {
        method: request.method,
        headers,
        body,
        signal: controller.signal,
        credentials: 'same-origin',
      });
      const responseHeaders: Record<string, string> = {};
      response.headers.forEach((value, key) => {
        responseHeaders[key.toLowerCase()] = value;
      });
      const type = responseHeaders['content-type'] ?? '';
      let parsed: unknown;
      if (type.includes('application/json')) parsed = await response.json().catch(() => null);
      else if (type.startsWith('text/') && !responseHeaders['content-disposition']) parsed = await response.text();
      else parsed = await response.blob();
      return { status: response.status, headers: responseHeaders, body: parsed };
    } catch (error) {
      if (timedOut) throw new TransportFailure('Сервер не ответил вовремя', 'timeout');
      if (request.signal?.aborted) throw new TransportFailure('Запрос отменен', 'aborted');
      throw new TransportFailure(
        error instanceof Error && error.message ? 'Нет связи с локальным сервером GlassFlow' : 'Нет связи с сервером',
        'offline',
      );
    } finally {
      if (timer) clearTimeout(timer);
      request.signal?.removeEventListener('abort', onAbort);
    }
  },
};

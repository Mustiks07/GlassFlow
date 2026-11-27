import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../api/client';
import { ApiError } from '../api/errors';
import { TransportFailure, type Transport, type TransportRequest, type TransportResponse } from '../api/transport';

function stub(handler: (req: TransportRequest) => TransportResponse | Promise<TransportResponse>) {
  const calls: TransportRequest[] = [];
  const transport: Transport = {
    kind: 'http',
    request: vi.fn(async (req: TransportRequest) => {
      calls.push(req);
      return handler(req);
    }),
  };
  return { transport, calls };
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    return error as ApiError;
  }
  throw new Error('expected the request to fail');
}

const json = (status: number, body: unknown, headers: Record<string, string> = {}): TransportResponse => ({ status, body, headers: { 'content-type': 'application/json', ...headers } });

describe('ApiClient', () => {
  it('sends the in-memory session token and idempotency key only on mutations', async () => {
    const { transport, calls } = stub(req => (req.path === '/session' ? json(200, { session_token: 'tok' }) : json(200, { ok: true })));
    const client = new ApiClient(transport);
    await client.get('/datasets');
    await client.post('/plans/P1/commit', { a: 1 }, { idempotencyKey: 'key-1' });
    const get = calls.find(c => c.path === '/datasets')!;
    const post = calls.find(c => c.path === '/plans/P1/commit')!;
    expect(get.headers['X-GlassFlow-Session']).toBeUndefined();
    expect(post.headers['X-GlassFlow-Session']).toBe('tok');
    expect(post.headers['Idempotency-Key']).toBe('key-1');
  });

  it('maps 409 envelopes to a conflict error with objects and correlation id', async () => {
    const { transport } = stub(req =>
      req.path === '/session'
        ? json(200, { session_token: 't' })
        : json(409, { code: 'VERSION_CONFLICT', message_ru: 'Версия изменилась', field_errors: [], conflict_objects: ['R006'], retryable: false, correlation_id: 'c-1' }),
    );
    const error = await failure(new ApiClient(transport).post('/quotes/Q/confirm', {}));
    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe('conflict');
    expect(error.conflictObjects).toEqual(['R006']);
    expect(error.correlationId).toBe('c-1');
    expect(error.message).toBe('Версия изменилась');
  });

  it('translates 422 field errors to Russian and maps them to form fields', async () => {
    const { transport } = stub(() => json(422, { code: 'VALIDATION_ERROR', message_ru: 'Проверьте поля запроса.', field_errors: [{ field: 'body.dimensions.length_mm', reason: 'int_type' }], correlation_id: 'c' }));
    const error: ApiError = await failure(new ApiClient(transport).get('/x'));
    expect(error.kind).toBe('validation');
    expect(error.fieldMessage('length_mm')).toBe('Нужно целое число');
  });

  it('exposes 429 Retry-After and 503 as retryable', async () => {
    const { transport } = stub(() => json(429, { code: 'RATE', message_ru: 'Лимит' }, { 'retry-after': '12' }));
    const error: ApiError = await failure(new ApiClient(transport).get('/x'));
    expect(error.kind).toBe('rate_limited');
    expect(error.retryAfterSeconds).toBe(12);
    expect(error.retryable).toBe(true);
  });

  it('refreshes the session once after LOCAL_SESSION_REQUIRED and retries', async () => {
    let tokens = 0;
    let attempts = 0;
    const { transport } = stub(req => {
      if (req.path === '/session') return json(200, { session_token: `t${++tokens}` });
      attempts += 1;
      return req.headers['X-GlassFlow-Session'] === 't2' ? json(200, { done: true }) : json(403, { code: 'LOCAL_SESSION_REQUIRED', message_ru: 'Сессия' });
    });
    const result = await new ApiClient(transport).post<{ done: boolean }>('/x', {});
    expect(result.done).toBe(true);
    expect(attempts).toBe(2);
  });

  it('turns a network failure into an offline error — no fallback data', async () => {
    const transport: Transport = { kind: 'http', request: async () => { throw new TransportFailure('down', 'offline'); } };
    const error: ApiError = await failure(new ApiClient(transport).get('/datasets'));
    expect(error.kind).toBe('offline');
    expect(error.message).toContain('Нет связи');
  });
});

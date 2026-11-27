export interface Health {
  status: 'ok';
  app: string;
  version: string;
}

export interface Readiness {
  status: string;
  database: boolean;
  business_modules_ready: boolean;
}

async function getJson(path: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(`/api/v1/${path}`, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`Сервер вернул HTTP ${response.status}`);
  return response.json();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export async function getHealth(signal: AbortSignal): Promise<Health> {
  const data = await getJson('health', signal);
  if (!isRecord(data) || data.status !== 'ok' || typeof data.app !== 'string' || typeof data.version !== 'string') {
    throw new Error('Ответ health не соответствует контракту');
  }
  return { status: 'ok', app: data.app, version: data.version };
}

export async function getReadiness(signal: AbortSignal): Promise<Readiness> {
  const data = await getJson('ready', signal);
  if (!isRecord(data) || typeof data.status !== 'string' || typeof data.database !== 'boolean' || typeof data.business_modules_ready !== 'boolean') {
    throw new Error('Ответ ready не соответствует контракту');
  }
  return { status: data.status, database: data.database, business_modules_ready: data.business_modules_ready };
}

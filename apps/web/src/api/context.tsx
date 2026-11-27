import { createContext, useContext, type ReactNode } from 'react';
import { ApiClient } from './client';
import { createEndpoints, type Endpoints } from './endpoints';
import { httpTransport, type Transport } from './transport';

export interface ApiContextValue {
  client: ApiClient;
  api: Endpoints;
  transportKind: Transport['kind'];
}

const ApiContext = createContext<ApiContextValue | null>(null);

export function makeApi(transport: Transport): ApiContextValue {
  const client = new ApiClient(transport);
  return { client, api: createEndpoints(client), transportKind: transport.kind };
}

/**
 * Resolves the transport from an explicit build flag only.
 * VITE_GLASSFLOW_TRANSPORT=fixture is used by `pnpm dev:fixture` and fixture E2E.
 * In a normal/production build the condition is statically false and the fixture
 * module is removed from the bundle (verified by tests/e2e/bundle-check).
 */
export async function resolveTransport(): Promise<Transport> {
  if (import.meta.env.VITE_GLASSFLOW_TRANSPORT === 'fixture') {
    const { createFixtureTransport } = await import('./fixtures/transport');
    return createFixtureTransport();
  }
  return httpTransport;
}

export function ApiProvider({ value, children }: { value: ApiContextValue; children: ReactNode }) {
  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>;
}

export function useApi(): ApiContextValue {
  const value = useContext(ApiContext);
  if (!value) throw new Error('ApiProvider is missing');
  return value;
}

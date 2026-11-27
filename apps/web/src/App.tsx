import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiProvider, type ApiContextValue } from './api/context';
import { asApiError } from './api/errors';
import { CuttingPage } from './features/cutting/CuttingPage';
import { ClientsPage } from './features/clients/ClientsPage';
import { ManagersPage } from './features/managers/ManagersPage';
import { RunsPage } from './features/runs/RunsPage';
import { SalesPage } from './features/sales/SalesPage';
import { SettingsPage } from './features/settings/SettingsPage';
import { Shell } from './features/shell/Shell';
import { WorkplacePage } from './features/workplace/WorkplacePage';
import { SECTIONS, useRoute } from './state/router';

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Never retry client errors (4xx/501): they will not fix themselves and must be shown.
        retry: (count, error) => {
          const e = asApiError(error);
          return count < 2 && (e.kind === 'offline' || e.kind === 'timeout' || e.kind === 'unavailable');
        },
        refetchOnWindowFocus: false,
        staleTime: 5_000,
      },
      mutations: { retry: false },
    },
  });
}

function Page() {
  const route = useRoute();
  useEffect(() => {
    const label = SECTIONS.find(section => section.id === route.section)?.label ?? 'GlassFlow';
    document.title = `${label} · GlassFlow`;
    document.getElementById('main-content')?.focus({ preventScroll: true });
  }, [route.section]);
  switch (route.section) {
    case 'cutting':
      return <CuttingPage />;
    case 'sales':
      return <SalesPage />;
    case 'clients':
      return <ClientsPage />;
    case 'managers':
      return <ManagersPage />;
    case 'runs':
      return <RunsPage />;
    case 'settings':
      return <SettingsPage sub={route.sub} />;
    default:
      return <WorkplacePage />;
  }
}

export function App({ api, queryClient }: { api: ApiContextValue; queryClient?: QueryClient }) {
  const [client] = useState(() => queryClient ?? createQueryClient());
  return (
    <ApiProvider value={api}>
      <QueryClientProvider client={client}>
        <Shell>
          <Page />
        </Shell>
      </QueryClientProvider>
    </ApiProvider>
  );
}

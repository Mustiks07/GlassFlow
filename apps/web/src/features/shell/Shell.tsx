import { useQuery } from '@tanstack/react-query';
import {
  Boxes,
  Copy,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  PlayCircle,
  Settings,
  Store,
  Users,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useApi } from '../../api/context';
import { newIdempotencyKey } from '../../api/client';
import type { Dataset } from '../../api/types';
import { useQueryClient, useMutation } from '@tanstack/react-query';
import { SECTIONS, href, navigate, type Section, useRoute } from '../../state/router';
import { useAppStore } from '../../state/store';
import { Button, ConfirmDialog, StatusBadge } from '../../ui/kit';
import { MODE_LABEL, MODE_SHORT, useCurrentDataset } from './dataset';
import { shortHash } from '../../lib/format';

const ICONS: Record<Section, typeof Boxes> = {
  workplace: LayoutDashboard,
  cutting: Boxes,
  sales: Store,
  clients: Users,
  managers: Gauge,
  runs: PlayCircle,
  settings: Settings,
};

export function Shell({ children }: { children: ReactNode }) {
  const route = useRoute();
  const { transportKind } = useApi();
  const active = SECTIONS.find(item => item.id === route.section) ?? SECTIONS[0];
  return (
    <div className="app">
      <a className="skip-link" href="#main-content">
        К содержимому
      </a>
      <aside className="sidebar">
        <a className="brand" href={href('workplace')} aria-label="GlassFlow, рабочее место">
          <span className="brand-symbol" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span>
            GlassFlow<small>Рабочее место KSM</small>
          </span>
        </a>
        <nav aria-label="Основная навигация">
          <ul>
            {SECTIONS.map(section => {
              const Icon = ICONS[section.id];
              const current = section.id === route.section;
              return (
                <li key={section.id}>
                  <a className={current ? 'nav-item active' : 'nav-item'} href={href(section.id)} aria-current={current ? 'page' : undefined}>
                    <Icon size={17} aria-hidden="true" />
                    <span>
                      {section.label}
                      <small>{section.short}</small>
                    </span>
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>
        <ReadinessFooter />
      </aside>
      <div className="main-shell">
        {transportKind === 'fixture' && (
          <div className="fixture-banner" role="note">
            <FlaskConical size={15} aria-hidden="true" /> ТЕСТОВЫЙ РЕЖИМ FIXTURE: данные из изолированного тестового адаптера, не
            результат backend. Для приемки используйте обычную сборку.
          </div>
        )}
        <header className="topbar">
          <div className="crumbs">
            <span className="crumb-app">GlassFlow</span>
            <span aria-hidden="true">/</span>
            <span className="crumb-page">{active.label}</span>
          </div>
          <DatasetSwitcher />
        </header>
        <main id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}

function ReadinessFooter() {
  const { api } = useApi();
  const ready = useQuery({ queryKey: ['ready'], queryFn: ({ signal }) => api.ready(signal), refetchInterval: 30_000, retry: 0 });
  let tone: 'ok' | 'warn' | 'error' | 'pending' = 'pending';
  let text = 'Проверка API…';
  if (ready.isError) {
    tone = 'error';
    text = 'API недоступен';
  } else if (ready.data) {
    tone = ready.data.status === 'ready' ? 'ok' : 'warn';
    text = ready.data.status === 'ready' ? 'Готово' : ready.data.status === 'degraded' ? 'Частично готово' : 'Каркас: модули не готовы';
  }
  return (
    <div className="sidebar-foot" aria-live="polite">
      <StatusBadge tone={tone}>{text}</StatusBadge>
      {ready.data && (
        <small>
          БД: {ready.data.database ? 'подключена' : 'не готова'}
          {ready.data.ai_available !== undefined && ` · AI: ${ready.data.ai_available ? 'доступен' : 'ограничен'}`}
        </small>
      )}
      {ready.isError && (
        <button className="link-btn" onClick={() => ready.refetch()}>
          Проверить снова
        </button>
      )}
    </div>
  );
}

function DatasetSwitcher() {
  const { dataset, datasets, datasetId, missing } = useCurrentDataset();
  const setDataset = useAppStore(state => state.setDataset);
  return (
    <div className="dataset-switcher">
      <label htmlFor="dataset-select" className="visually-hidden">
        Набор данных
      </label>
      <select
        id="dataset-select"
        value={datasetId ?? ''}
        onChange={event => setDataset(event.target.value || null)}
        disabled={datasets.isLoading || datasets.isError}
      >
        <option value="">{datasets.isLoading ? 'Загрузка наборов…' : datasets.isError ? 'Наборы недоступны' : 'Выберите набор данных'}</option>
        {datasets.data?.map(item => (
          <option key={item.dataset_id} value={item.dataset_id}>
            {item.name} · {MODE_SHORT[item.mode]}
          </option>
        ))}
      </select>
      {dataset ? <ModeBadge dataset={dataset} /> : <StatusBadge tone={missing ? 'error' : 'neutral'}>{missing ? 'Набор удален' : 'Набор не выбран'}</StatusBadge>}
      {dataset && dataset.mode !== 'workspace' && <WorkingCopyButton dataset={dataset} />}
    </div>
  );
}

export function ModeBadge({ dataset }: { dataset: Dataset }) {
  return (
    <span className={`mode-badge mode-${dataset.mode}`} title={`dataset_id ${dataset.dataset_id}`}>
      {MODE_LABEL[dataset.mode]}
      <span className="mono"> · {shortHash(dataset.dataset_id, 8)}</span>
    </span>
  );
}

export function WorkingCopyButton({ dataset, label = 'Рабочая копия' }: { dataset: Dataset; label?: string }) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const setDataset = useAppStore(state => state.setDataset);
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const mutation = useMutation({
    mutationFn: () => api.createWorkingCopy(dataset.dataset_id, `Рабочая копия · ${dataset.name}`, key),
    onSuccess: created => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] });
      setDataset(created.dataset_id);
      setOpen(false);
      setKey(newIdempotencyKey());
      navigate('workplace');
    },
  });
  return (
    <>
      <Button icon={<Copy size={14} aria-hidden="true" />} onClick={() => setOpen(true)}>
        {label}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={value => {
          setOpen(value);
          if (!value) mutation.reset();
        }}
        title="Создать рабочую копию"
        action="Будет создан новый изменяемый набор. Исходный снимок останется неизменным; резервы, замеры и цены рабочей копии не попадут в конкурсный прогон."
        affected={[
          { label: 'Источник', value: dataset.name },
          { label: 'Режим источника', value: MODE_LABEL[dataset.mode] },
          { label: 'dataset_id', value: <span className="mono">{dataset.dataset_id}</span> },
        ]}
        confirmLabel="Создать рабочую копию"
        onConfirm={() => mutation.mutate()}
        busy={mutation.isPending}
        error={mutation.error}
      />
    </>
  );
}

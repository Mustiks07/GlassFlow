import { href } from '../../state/router';
import { AiSection } from './AiSection';
import { DataSection } from './DataSection';
import { SystemSection } from './SystemSection';

const TABS = [
  { id: 'data', label: 'Данные и импорт' },
  { id: 'ai', label: 'AI-профиль' },
  { id: 'system', label: 'Система' },
] as const;

export function SettingsPage({ sub }: { sub: string | null }) {
  const active = TABS.find(tab => tab.id === sub)?.id ?? 'data';
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Настройки</p>
          <h1>Данные, AI и система</h1>
          <p className="lead">Импорт неизменных снимков, рабочие копии, профиль AI без хранения ключа в браузере, резервные копии и журнал.</p>
        </div>
      </header>
      <nav className="tabs" aria-label="Разделы настроек">
        {TABS.map(tab => (
          <a key={tab.id} href={href('settings', tab.id)} className={tab.id === active ? 'tab active' : 'tab'} aria-current={tab.id === active ? 'page' : undefined}>
            {tab.label}
          </a>
        ))}
      </nav>
      {active === 'data' && <DataSection />}
      {active === 'ai' && <AiSection />}
      {active === 'system' && <SystemSection />}
    </div>
  );
}

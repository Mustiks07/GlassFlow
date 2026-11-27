import { useEffect, useState } from 'react';
import { getHealth, getReadiness, type Health, type Readiness } from './api';

const modules = [
  { name: 'Рабочее место', number: '01', description: 'Запрос клиента, проверенный расчет, подходящий остаток и следующее действие в одном контексте.' },
  { name: 'Остатки и раскрой', number: '02', description: 'Склад, места хранения, резервы и интерактивная схема размещения деталей.' },
  { name: 'Продажа остатков', number: '03', description: 'Карточки свободных кусков и реестр потенциальных покупателей с подтвержденными источниками.' },
  { name: 'Клиенты', number: '04', description: 'Приоритет повторных обращений и локальные напоминания с конкретным адресатом и предметом.' },
  { name: 'Менеджеры', number: '05', description: 'Семь исторических показателей M1–M5 с исходными строками и понятными знаменателями.' },
  { name: 'Прогоны', number: '06', description: 'Изолированные наборы, воспроизводимый расчет и проверенные конкурсные CSV.' },
  { name: 'Настройки', number: '07', description: 'Профили Gemini и OpenRouter, квоты, версии данных и параметры локального приложения.' },
];

type Connection = { phase: 'loading' } | { phase: 'ready'; health: Health; readiness: Readiness } | { phase: 'error'; message: string };

export function App() {
  const [selected, setSelected] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [connection, setConnection] = useState<Connection>({ phase: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setConnection({ phase: 'loading' });
    Promise.all([getHealth(controller.signal), getReadiness(controller.signal)])
      .then(([health, readiness]) => {
        if (!controller.signal.aborted) setConnection({ phase: 'ready', health, readiness });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setConnection({ phase: 'error', message: error instanceof Error ? error.message : 'Не удалось получить состояние API' });
      });
    return () => controller.abort();
  }, [attempt]);

  const active = modules[selected];
  return (
    <div className="workspace">
      <a className="skip-link" href="#main-content">К содержимому</a>
      <aside className="sidebar">
        <a className="brand" href="#main-content" aria-label="GlassFlow, к содержимому">
          <span className="brand-symbol" aria-hidden="true"><i /><i /><i /></span>
          <span>GlassFlow<small>Рабочее место KSM</small></span>
        </a>
        <div className="sidebar-caption">РАЗДЕЛЫ ПРОЕКТА</div>
        <nav aria-label="Разделы проекта">
          {modules.map((module, index) => (
            <button key={module.number} className={selected === index ? 'nav-item active' : 'nav-item'} aria-pressed={selected === index} onClick={() => setSelected(index)}>
              <span className="nav-number" aria-hidden="true">{module.number}</span><span>{module.name}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom"><span className="small-dot" aria-hidden="true" /> Общая база разработки<small>GENESIS · 2026</small></div>
      </aside>
      <div className="main-shell">
        <header className="topbar"><span>GlassFlow <span className="breadcrumb">/ {active.name}</span></span><span className="stage-badge">Каркас проекта</span></header>
        <main id="main-content" tabIndex={-1}>
          <div className="eyebrow">ОТ ОСТАТКА ДО КЛИЕНТА</div>
          <h1>{active.name}</h1>
          <p className="intro">{active.description}</p>
          <section className="foundation-panel" aria-labelledby="foundation-heading">
            <div className="panel-marker" aria-hidden="true">G</div>
            <div><span className="section-label">ОБЩАЯ ТОЧКА СТАРТА</span><h2 id="foundation-heading">Основа готова к разработке</h2>
              <p>Этот экран проверяет запуск интерфейса и связь с API. Бизнес-модули еще не реализованы: здесь нет демонстрационных продаж, резервов или результатов раскроя.</p>
            </div>
          </section>
          <section className="connection-panel" aria-labelledby="connection-heading">
            <div className="panel-title"><h2 id="connection-heading">Состояние приложения</h2><button className="refresh-button" disabled={connection.phase === 'loading'} onClick={() => setAttempt(value => value + 1)}>Проверить связь</button></div>
            <div role="status" aria-live="polite">
              {connection.phase === 'loading' && <p className="status-message">Проверяем локальный API…</p>}
              {connection.phase === 'error' && <div className="error-message"><strong>API недоступен</strong><p>{connection.message}. Запустите backend по инструкции в README и повторите проверку.</p></div>}
              {connection.phase === 'ready' && <div className="status-grid">
                <Status label="Сервер API" value="Доступен" detail={`${connection.health.app} · ${connection.health.version}`} good />
                <Status label="База данных" value={connection.readiness.database ? 'Подключена' : 'Не готова'} detail="Ответ /api/v1/ready" good={connection.readiness.database} />
                <Status label="Бизнес-модули" value={connection.readiness.business_modules_ready ? 'API сообщает готовность' : 'Ожидают реализации'} detail={`Профиль: ${connection.readiness.status}`} good={connection.readiness.business_modules_ready} />
              </div>}
            </div>
          </section>
          <section className="next-panel" aria-labelledby="next-heading"><span className="section-label">СЛЕДУЮЩИЙ ЭТАП</span><h2 id="next-heading">Четыре направления, один продукт</h2>
            <div className="tracks"><Track name="Интерфейс" detail="Рабочие сценарии и визуальная проверка" /><Track name="Склад и раскрой" detail="Геометрия, резервы и оптимизация" /><Track name="Каталог и AI" detail="Точные цены и проверяемые ответы" /><Track name="Платформа и CRM" detail="Данные, аналитика, экспорт и поставка" /></div>
            <p className="footnote">Контекст и задания находятся в документации репозитория. Все направления начинают работу от общей базы и развиваются в отдельных ветках.</p>
          </section>
        </main>
      </div>
    </div>
  );
}

function Status({ label, value, detail, good }: { label: string; value: string; detail: string; good: boolean }) {
  return <div className="status-item"><span className="status-label">{label}</span><strong><span className={good ? 'status-dot good' : 'status-dot pending'} aria-hidden="true" />{value}</strong><small>{detail}</small></div>;
}

function Track({ name, detail }: { name: string; detail: string }) {
  return <div className="track"><h3>{name}</h3><p>{detail}</p><span className="pending-label">Запланировано</span></div>;
}

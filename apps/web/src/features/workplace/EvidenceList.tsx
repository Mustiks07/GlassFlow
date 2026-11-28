import type { Evidence } from '../../api/types';

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (!evidence.length) return <p className="small muted">Источники не переданы.</p>;
  return (
    <ul className="evidence small">
      {evidence.map((item, index) => (
        <li key={index}>
          <span className="mono">{item.source}</span>
          {item.record_id && (
            <>
              {' '}
              · запись <span className="mono">{item.record_id}</span>
            </>
          )}
          {item.field && (
            <>
              {' '}
              · поле <span className="mono">{item.field}</span>
            </>
          )}
          <span className="muted"> · версия {item.source_version.replace(/^sha256:/, '').slice(0, 12)}</span>
        </li>
      ))}
    </ul>
  );
}

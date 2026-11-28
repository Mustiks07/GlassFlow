import type { Evidence } from '../../api/types';
import { Details } from '../../ui/kit';

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (!evidence.length) return <p className="small muted">Источники не переданы.</p>;
  return (
    <ul className="evidence small">
      {evidence.map((item, index) => (
        <li key={index}>
          <span>{/kb|knowledge|каталог/i.test(item.source) ? 'База знаний: прайс и правила' : /material/i.test(item.source) ? 'Справочник материалов' : /stock|remnant/i.test(item.source) ? 'Текущий склад' : 'Проверяемый источник расчёта'}</span>
          <Details summary="Сведения об источнике для проверки"><span className="mono">{item.source}{item.record_id ? ` · запись ${item.record_id}` : ''}{item.field ? ` · поле ${item.field}` : ''} · версия {item.source_version}</span></Details>
        </li>
      ))}
    </ul>
  );
}

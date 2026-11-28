import { Grid3x3, Lock, LockOpen, Minus, Plus, RotateCw } from 'lucide-react';
import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import type { Part, Placement, Remnant } from '../../api/types';
import { formatDims } from '../../lib/format';
import { Button, Details, StatusBadge, TableWrap } from '../../ui/kit';
import { RemnantSvg, footprint, previewViolations, type SvgPart } from './RemnantSvg';
import { parseLocation } from './labels';
import { useCuttingStore } from './draftStore';

interface Props {
  remnant: Remnant;
  materialName?: string;
  tempered: boolean;
  placements: Placement[];
  parts: Map<string, Part>;
  /** Server-reported invalid part ids from the last validation of the draft. */
  invalidPartIds: Set<string>;
  editable: boolean;
  candidateRemnants: Remnant[];
  onChange: (placement: Placement) => void;
}

export function SchemeEditor({ remnant, materialName, tempered, placements, parts, invalidPartIds, editable, candidateRemnants, onChange }: Props) {
  const { zoom, setZoom, showGap, toggleGap, selectedPartId, selectPart } = useCuttingStore();
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ partId: string; dx: number; dy: number; x: number; y: number } | null>(null);
  const location = parseLocation(remnant.location_raw);

  const svgParts: SvgPart[] = useMemo(
    () =>
      placements.map(placement => {
        const part = parts.get(placement.part_id);
        const dims = part?.dimensions ?? { length_mm: 0, width_mm: 0 };
        const fp = footprint(dims.length_mm, dims.width_mm, placement.rot);
        const dragging = drag?.partId === placement.part_id;
        return {
          part_id: placement.part_id,
          x_mm: dragging ? drag.x : placement.x_mm ?? 0,
          y_mm: dragging ? drag.y : placement.y_mm ?? 0,
          w_mm: fp.w,
          h_mm: fp.h,
          rot: (placement.rot ?? 0) as 0 | 1,
          state: invalidPartIds.has(placement.part_id)
            ? 'invalid'
            : placement.lock_kind === 'placement'
              ? 'locked_placement'
              : placement.lock_kind === 'assignment'
                ? 'locked_assignment'
                : 'ok',
        } satisfies SvgPart;
      }),
    [placements, parts, drag, invalidPartIds],
  );

  // Local preview reasons (server decides validity).
  const violations = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const part of svgParts) map.set(part.part_id, previewViolations({ remnant_id: remnant.remnant_id, length_mm: remnant.dimensions.length_mm, width_mm: remnant.dimensions.width_mm, tempered }, part, svgParts));
    return map;
  }, [svgParts, remnant, tempered]);
  const shown = svgParts.map(part => (violations.get(part.part_id)?.length && part.state !== 'invalid' ? { ...part, state: 'invalid' as const } : part));

  const toMm = (event: { clientX: number; clientY: number }) => {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return null;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse());
    return { x: point.x, y: point.y };
  };

  const placementOf = (partId: string) => placements.find(item => item.part_id === partId);

  const onPointerDown = (part: SvgPart, event: ReactPointerEvent<SVGGElement>) => {
    selectPart(part.part_id);
    const placement = placementOf(part.part_id);
    if (!editable || tempered || placement?.lock_kind === 'placement') return;
    const point = toMm(event);
    if (!point) return;
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
    setDrag({ partId: part.part_id, dx: point.x - part.x_mm, dy: point.y - part.y_mm, x: part.x_mm, y: part.y_mm });
  };
  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!drag) return;
    const point = toMm(event);
    if (!point) return;
    setDrag({ ...drag, x: Math.max(0, Math.round(point.x - drag.dx)), y: Math.max(0, Math.round(point.y - drag.dy)) });
  };
  const onPointerUp = () => {
    if (!drag) return;
    const placement = placementOf(drag.partId);
    if (placement && (placement.x_mm !== drag.x || placement.y_mm !== drag.y)) onChange({ ...placement, x_mm: drag.x, y_mm: drag.y });
    setDrag(null);
  };

  const nudge = (partId: string, dx: number, dy: number) => {
    const placement = placementOf(partId);
    if (!placement || placement.lock_kind === 'placement' || tempered) return;
    onChange({ ...placement, x_mm: Math.max(0, (placement.x_mm ?? 0) + dx), y_mm: Math.max(0, (placement.y_mm ?? 0) + dy) });
  };
  const rotate = (partId: string) => {
    const placement = placementOf(partId);
    if (!placement || placement.lock_kind === 'placement') return;
    onChange({ ...placement, rot: placement.rot === 1 ? 0 : 1 });
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!selectedPartId || !editable) return;
    const step = event.shiftKey ? 10 : 1;
    const moves: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[event.key]) {
      event.preventDefault();
      nudge(selectedPartId, ...moves[event.key]);
    } else if (event.key === 'r' || event.key === 'R' || event.key === 'к' || event.key === 'К') {
      event.preventDefault();
      rotate(selectedPartId);
    } else if (event.key === 'Escape') selectPart(null);
  };

  const selected = selectedPartId ? placementOf(selectedPartId) : undefined;
  const selectedReasons = selectedPartId ? violations.get(selectedPartId) ?? [] : [];

  return (
    <div className="scheme-editor">
      <div className="scheme-head">
        <div>
          <strong className="mono">{remnant.remnant_id}</strong> · {formatDims(remnant.dimensions)} · {materialName ?? 'Материал уточняется'}<Details summary="Код материала для поддержки">{remnant.material_id}</Details>
          {tempered && <StatusBadge tone="info">Калёное</StatusBadge>}
          {remnant.defect && <StatusBadge tone="warn">Дефект (геометрия неизвестна)</StatusBadge>}
          <div className="small muted">
            Место: {remnant.location_raw}
            {location.rack && ` · стеллаж ${location.rack}`}
            {location.cell && `, ячейка ${location.cell}`}
          </div>
        </div>
        <div className="row" role="toolbar" aria-label="Масштаб схемы">
          <Button variant="ghost" icon={<Minus size={14} aria-hidden="true" />} onClick={() => setZoom(zoom - 0.25)} aria-label="Уменьшить">
            {''}
          </Button>
          <span className="small mono" aria-live="polite">
            {Math.round(zoom * 100)}%
          </span>
          <Button variant="ghost" icon={<Plus size={14} aria-hidden="true" />} onClick={() => setZoom(zoom + 0.25)} aria-label="Увеличить">
            {''}
          </Button>
          <Button variant="ghost" icon={<Grid3x3 size={14} aria-hidden="true" />} onClick={toggleGap} aria-pressed={showGap}>
            Зазор 3 мм
          </Button>
        </div>
      </div>
      <div
        className="scheme-canvas"
        tabIndex={0}
        role="group"
        aria-label={`Схема остатка ${remnant.remnant_id}. Стрелки — сдвиг выбранной детали на 1 мм (Shift — 10 мм), R — поворот, Escape — снять выбор.`}
        onKeyDown={onKeyDown}
      >
        <div onPointerMove={onPointerMove as never} onPointerUp={onPointerUp} onPointerCancel={() => setDrag(null)}>
          <RemnantSvg
            svgRef={svgRef}
            remnant={{ remnant_id: remnant.remnant_id, length_mm: remnant.dimensions.length_mm, width_mm: remnant.dimensions.width_mm, tempered, defect: remnant.defect }}
            parts={shown}
            selectedPartId={selectedPartId}
            zoom={zoom}
            showGap={showGap}
            onPartPointerDown={onPointerDown}
          />
        </div>
      </div>
      <ul className="legend small" aria-label="Легенда">
        <li>
          <i className="lg lg-ok" /> размещение
        </li>
        <li>
          <i className="lg lg-invalid" /> недопустимо (штриховка)
        </li>
        <li>
          <i className="lg lg-lockp" /> закреплено размещение
        </li>
        <li>
          <i className="lg lg-locka" /> закреплено назначение
        </li>
        <li>
          <i className="lg lg-edge" /> рабочий край 5 мм
        </li>
      </ul>
      {selected && (
        <div className="selected-part" aria-live="polite">
          <strong className="mono">{selected.part_id}</strong>
          {selectedReasons.length > 0 ? (
            <span className="text-error small"> — предварительно недопустимо: {selectedReasons.join('; ')}. Черновик можно исправить; активный план не меняется.</span>
          ) : (
            <span className="small muted"> — локальная проверка пройдена; окончательно решает сервер.</span>
          )}
          {editable && (
            <div className="row">
              <Button variant="ghost" icon={<RotateCw size={14} aria-hidden="true" />} onClick={() => rotate(selected.part_id)} disabled={selected.lock_kind === 'placement'}>
                Повернуть
              </Button>
              <Button
                variant="ghost"
                icon={selected.lock_kind === 'none' ? <Lock size={14} aria-hidden="true" /> : <LockOpen size={14} aria-hidden="true" />}
                onClick={() => onChange({ ...selected, lock_kind: selected.lock_kind === 'none' ? 'placement' : selected.lock_kind === 'placement' ? 'assignment' : 'none' })}
              >
                {selected.lock_kind === 'none' ? 'Закрепить размещение' : selected.lock_kind === 'placement' ? 'Закрепить только назначение' : 'Снять закрепление'}
              </Button>
            </div>
          )}
        </div>
      )}
      <PlacementTable
        placements={placements}
        parts={parts}
        violations={violations}
        invalidPartIds={invalidPartIds}
        editable={editable}
        tempered={tempered}
        remnant={remnant}
        candidateRemnants={candidateRemnants}
        onChange={onChange}
      />
    </div>
  );
}

/** Table alternative to the SVG; also the keyboard-only editing path. */
function PlacementTable({
  placements,
  parts,
  violations,
  invalidPartIds,
  editable,
  tempered,
  remnant,
  candidateRemnants,
  onChange,
}: {
  placements: Placement[];
  parts: Map<string, Part>;
  violations: Map<string, string[]>;
  invalidPartIds: Set<string>;
  editable: boolean;
  tempered: boolean;
  remnant: Remnant;
  candidateRemnants: Remnant[];
  onChange: (placement: Placement) => void;
}) {
  const { selectedPartId, selectPart } = useCuttingStore();
  if (!placements.length) return <p className="small muted">На этом остатке нет деталей в выбранной версии плана.</p>;
  return (
    <TableWrap label={`Размещения на ${remnant.remnant_id}`}>
      <table className="table compact">
        <caption className="visually-hidden">Табличная альтернатива схемы {remnant.remnant_id}</caption>
        <thead>
          <tr>
            <th scope="col">Деталь</th>
            <th scope="col">Заказ</th>
            <th scope="col">Размер</th>
            <th scope="col">x, мм</th>
            <th scope="col">y, мм</th>
            <th scope="col">Поворот</th>
            <th scope="col">Закрепление</th>
            <th scope="col">Остаток</th>
            <th scope="col">Проверка</th>
          </tr>
        </thead>
        <tbody>
          {placements.map(placement => {
            const part = parts.get(placement.part_id);
            const reasons = violations.get(placement.part_id) ?? [];
            const locked = placement.lock_kind === 'placement';
            return (
              <tr key={placement.part_id} aria-selected={selectedPartId === placement.part_id} onClick={() => selectPart(placement.part_id)}>
                <th scope="row" className="mono">
                  {placement.part_id}
                  {part?.premium && <span className="small"> · премиум</span>}
                </th>
                <td className="mono">{part?.order_id ?? '—'}</td>
                <td>{part ? formatDims(part.dimensions) : '—'}</td>
                <td>
                  <NumberCell
                    label={`x для ${placement.part_id}`}
                    value={placement.x_mm}
                    disabled={!editable || locked || tempered}
                    onCommit={value => onChange({ ...placement, x_mm: value })}
                  />
                </td>
                <td>
                  <NumberCell
                    label={`y для ${placement.part_id}`}
                    value={placement.y_mm}
                    disabled={!editable || locked || tempered}
                    onCommit={value => onChange({ ...placement, y_mm: value })}
                  />
                </td>
                <td>
                  <select
                    aria-label={`Поворот ${placement.part_id}`}
                    value={placement.rot ?? 0}
                    disabled={!editable || locked}
                    onChange={event => onChange({ ...placement, rot: Number(event.target.value) as 0 | 1 })}
                  >
                    <option value={0}>0°</option>
                    <option value={1}>90°</option>
                  </select>
                </td>
                <td>
                  <select
                    aria-label={`Закрепление ${placement.part_id}`}
                    value={placement.lock_kind}
                    disabled={!editable}
                    onChange={event => onChange({ ...placement, lock_kind: event.target.value as Placement['lock_kind'] })}
                  >
                    <option value="none">нет</option>
                    <option value="assignment">назначение</option>
                    <option value="placement">размещение</option>
                  </select>
                </td>
                <td>
                  <select
                    aria-label={`Остаток для ${placement.part_id}`}
                    value={placement.remnant_id}
                    disabled={!editable || placement.lock_kind !== 'none'}
                    onChange={event =>
                      onChange({
                        ...placement,
                        remnant_id: event.target.value,
                        ...(event.target.value === 'NEW' ? { x_mm: null, y_mm: null, rot: null } : { x_mm: 5, y_mm: 5 }),
                      })
                    }
                  >
                    <option value={remnant.remnant_id}>{remnant.remnant_id}</option>
                    {candidateRemnants
                      .filter(item => item.remnant_id !== remnant.remnant_id)
                      .map(item => (
                        <option key={item.remnant_id} value={item.remnant_id}>
                          {item.remnant_id} ({item.dimensions.length_mm}×{item.dimensions.width_mm})
                        </option>
                      ))}
                    <option value="NEW">Новый материал (не размещать на остатке)</option>
                  </select>
                </td>
                <td className="small">
                  {invalidPartIds.has(placement.part_id) ? (
                    <StatusBadge tone="error">сервер: недопустимо</StatusBadge>
                  ) : reasons.length ? (
                    <span className="text-error">{reasons.join('; ')}</span>
                  ) : (
                    <StatusBadge tone="neutral">локально ок</StatusBadge>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableWrap>
  );
}

function NumberCell({ label, value, disabled, onCommit }: { label: string; value: number | null | undefined; disabled: boolean; onCommit: (value: number) => void }) {
  const [text, setText] = useState<string | null>(null);
  const shown = text ?? (value === null || value === undefined ? '' : String(value));
  const commit = () => {
    if (text === null) return;
    if (/^\d+$/.test(text)) onCommit(Number(text));
    setText(null);
  };
  return (
    <input
      className="cell-input"
      aria-label={label}
      inputMode="numeric"
      value={shown}
      disabled={disabled}
      aria-invalid={text !== null && !/^\d+$/.test(text) ? true : undefined}
      onChange={event => setText(event.target.value)}
      onBlur={commit}
      onKeyDown={event => {
        if (event.key === 'Enter') commit();
        if (event.key === 'Escape') setText(null);
      }}
    />
  );
}

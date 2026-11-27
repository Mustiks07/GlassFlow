import { useId, type PointerEvent as ReactPointerEvent } from 'react';
import { formatInt } from '../../lib/format';

export const EDGE_MM = 5;
export const GAP_MM = 3;

export interface SvgPart {
  part_id: string;
  x_mm: number;
  y_mm: number;
  /** Footprint along x/y after rotation. */
  w_mm: number;
  h_mm: number;
  rot: 0 | 1;
  state?: 'ok' | 'invalid' | 'draft' | 'locked_placement' | 'locked_assignment' | 'candidate';
  label?: string;
}

export interface SvgRemnant {
  remnant_id: string;
  length_mm: number;
  width_mm: number;
  tempered?: boolean;
  defect?: boolean;
}

/**
 * Native SVG remnant scheme in millimetre coordinates (origin = top-left corner of
 * the remnant, x along length, y along width, as in the case rules). The 5 mm working
 * edge and the 3 mm keep-out around parts are drawn from the same constants the
 * backend validator uses; the drawing is a preview — the server decides validity.
 *
 * Tempered remnants: no working edge and no cut lines; the whole piece is the part.
 * Defect geometry is unknown, so no "safe area" is ever drawn.
 */
export function RemnantSvg({
  remnant,
  parts,
  selectedPartId,
  zoom = 1,
  showGap = false,
  title,
  onPartPointerDown,
  onPartSelect,
  svgRef,
  maxHeight = 420,
}: {
  remnant: SvgRemnant;
  parts: SvgPart[];
  selectedPartId?: string | null;
  zoom?: number;
  showGap?: boolean;
  title?: string;
  onPartPointerDown?: (part: SvgPart, event: ReactPointerEvent<SVGGElement>) => void;
  onPartSelect?: (part: SvgPart) => void;
  svgRef?: React.Ref<SVGSVGElement>;
  maxHeight?: number;
}) {
  const titleId = useId();
  const L = remnant.length_mm;
  const W = remnant.width_mm;
  const pad = Math.max(L, W) * 0.09;
  const font = Math.max(L, W) / 38;
  const scaleBar = niceScale(L);
  const viewBox = `${-pad} ${-pad} ${L + pad * 1.6} ${W + pad * 2}`;
  const heightPx = Math.min(maxHeight, 520) * zoom;
  return (
    <svg
      ref={svgRef}
      className="remnant-svg"
      viewBox={viewBox}
      style={{ height: heightPx, maxWidth: zoom > 1 ? 'none' : '100%' }}
      role="img"
      aria-labelledby={titleId}
      preserveAspectRatio="xMidYMid meet"
    >
      <title id={titleId}>
        {title ?? `Остаток ${remnant.remnant_id}, ${L} на ${W} мм, деталей: ${parts.length}`}
      </title>
      <defs>
        <pattern id={`${titleId}-hatch`} width={font * 0.8} height={font * 0.8} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2={font * 0.8} className="svg-hatch" />
        </pattern>
      </defs>
      {/* outer remnant */}
      <rect x={0} y={0} width={L} height={W} className={remnant.tempered ? 'svg-remnant tempered' : 'svg-remnant'} />
      {/* working edge */}
      {!remnant.tempered && L > 2 * EDGE_MM && W > 2 * EDGE_MM && (
        <rect x={EDGE_MM} y={EDGE_MM} width={L - 2 * EDGE_MM} height={W - 2 * EDGE_MM} className="svg-edge" />
      )}
      {/* outer dimensions */}
      <text x={L / 2} y={-pad * 0.35} className="svg-dim" fontSize={font} textAnchor="middle">
        {formatInt(L)} мм
      </text>
      <text x={-pad * 0.35} y={W / 2} className="svg-dim" fontSize={font} textAnchor="middle" transform={`rotate(-90 ${-pad * 0.35} ${W / 2})`}>
        {formatInt(W)} мм
      </text>
      {parts.map(part => {
        const selected = part.part_id === selectedPartId;
        const cls = `svg-part state-${part.state ?? 'ok'}${selected ? ' selected' : ''}`;
        return (
          <g
            key={part.part_id}
            className={onPartPointerDown ? 'svg-part-group draggable' : 'svg-part-group'}
            onPointerDown={onPartPointerDown ? event => onPartPointerDown(part, event) : undefined}
            onClick={onPartSelect ? () => onPartSelect(part) : undefined}
            data-part-id={part.part_id}
          >
            {showGap && !remnant.tempered && (
              <rect
                x={part.x_mm - GAP_MM}
                y={part.y_mm - GAP_MM}
                width={part.w_mm + 2 * GAP_MM}
                height={part.h_mm + 2 * GAP_MM}
                className="svg-gap"
              />
            )}
            <rect x={part.x_mm} y={part.y_mm} width={part.w_mm} height={part.h_mm} className={cls} />
            {part.state === 'invalid' && (
              <rect x={part.x_mm} y={part.y_mm} width={part.w_mm} height={part.h_mm} fill={`url(#${titleId}-hatch)`} className="svg-invalid-overlay" />
            )}
            {part.w_mm > font * 3 && part.h_mm > font * 1.6 && (
              <>
                <text x={part.x_mm + part.w_mm / 2} y={part.y_mm + part.h_mm / 2 - font * 0.15} fontSize={font * 0.9} textAnchor="middle" className="svg-part-label">
                  {part.label ?? part.part_id}
                  {part.rot ? ' ⟲' : ''}
                </text>
                <text x={part.x_mm + part.w_mm / 2} y={part.y_mm + part.h_mm / 2 + font * 0.95} fontSize={font * 0.75} textAnchor="middle" className="svg-part-dims">
                  {formatInt(part.w_mm)}×{formatInt(part.h_mm)}
                </text>
              </>
            )}
          </g>
        );
      })}
      {remnant.tempered && (
        <text x={L / 2} y={W + pad * 0.55} fontSize={font * 0.85} textAnchor="middle" className="svg-note">
          Калёное: деталь целиком, допуск ±2 мм, без резки
        </text>
      )}
      {/* scale bar */}
      <g transform={`translate(0 ${W + pad * (remnant.tempered ? 1.2 : 0.6)})`}>
        <line x1={0} y1={0} x2={scaleBar} y2={0} className="svg-scale" />
        <line x1={0} y1={-font * 0.3} x2={0} y2={font * 0.3} className="svg-scale" />
        <line x1={scaleBar} y1={-font * 0.3} x2={scaleBar} y2={font * 0.3} className="svg-scale" />
        <text x={scaleBar + font * 0.4} y={font * 0.35} fontSize={font * 0.8} className="svg-dim">
          {formatInt(scaleBar)} мм
        </text>
      </g>
    </svg>
  );
}

function niceScale(length: number): number {
  const target = length / 4;
  const steps = [10, 20, 50, 100, 200, 250, 500, 1000, 2000];
  return steps.reduce((best, step) => (Math.abs(step - target) < Math.abs(best - target) ? step : best), steps[0]);
}

/** Footprint of a part on the remnant: rot=0 → x along part length. */
export function footprint(length_mm: number, width_mm: number, rot: 0 | 1 | null | undefined) {
  return rot === 1 ? { w: width_mm, h: length_mm } : { w: length_mm, h: width_mm };
}

/**
 * Local preview check only (spec §6: the server decides). Mirrors the case rules
 * so the user sees a reason immediately while dragging.
 */
export function previewViolations(remnant: SvgRemnant, part: SvgPart, others: SvgPart[]): string[] {
  const reasons: string[] = [];
  if (remnant.tempered) return reasons; // tempered rules are checked by the server (whole piece ±2 mm)
  if (part.x_mm < EDGE_MM || part.y_mm < EDGE_MM) reasons.push('ближе 5 мм к краю остатка');
  if (part.x_mm + part.w_mm > remnant.length_mm - EDGE_MM || part.y_mm + part.h_mm > remnant.width_mm - EDGE_MM)
    reasons.push('выходит за рабочую зону (край 5 мм)');
  for (const other of others) {
    if (other.part_id === part.part_id) continue;
    const separated =
      part.x_mm + part.w_mm + GAP_MM <= other.x_mm ||
      other.x_mm + other.w_mm + GAP_MM <= part.x_mm ||
      part.y_mm + part.h_mm + GAP_MM <= other.y_mm ||
      other.y_mm + other.h_mm + GAP_MM <= part.y_mm;
    if (!separated) reasons.push(`зазор с ${other.part_id} меньше 3 мм или пересечение`);
  }
  return reasons;
}

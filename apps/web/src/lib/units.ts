/**
 * Dimension input parsing (spec §21): millimetres by default; explicitly written
 * cm/m are converted and the original + normalized value are shown. Anything
 * that does not give an exact positive integer number of millimetres is an
 * ambiguity that needs clarification — we never round silently.
 */

export type Unit = 'mm' | 'cm' | 'm';

export type ParsedLength =
  | { ok: true; mm: number; unit: Unit; explicitUnit: boolean; original: string; converted: boolean }
  | { ok: false; original: string; reason: string };

const UNIT_ALIASES: Record<string, Unit> = {
  мм: 'mm',
  mm: 'mm',
  см: 'cm',
  cm: 'cm',
  м: 'm',
  m: 'm',
  метр: 'm',
  метра: 'm',
  метров: 'm',
  сантиметр: 'cm',
  сантиметра: 'cm',
  сантиметров: 'cm',
  миллиметр: 'mm',
  миллиметра: 'mm',
  миллиметров: 'mm',
};

const FACTOR: Record<Unit, number> = { mm: 1, cm: 10, m: 1000 };

/** Exact decimal × integer factor using string digits (avoids 0.1*3 style errors). */
function toMillimetres(numberText: string, unit: Unit): number | null {
  const [whole, fraction = ''] = numberText.split('.');
  const scale = FACTOR[unit];
  const scaleDigits = Math.log10(scale);
  if (fraction.length > scaleDigits) {
    // e.g. 45,55 см = 455,5 мм — not an integer number of millimetres
    const extra = fraction.slice(scaleDigits);
    if (/[1-9]/.test(extra)) return null;
  }
  const padded = (fraction + '000').slice(0, scaleDigits);
  const digits = `${whole}${padded}`.replace(/^0+(?=\d)/, '');
  const value = Number(digits);
  return Number.isSafeInteger(value) ? value : null;
}

export function parseLength(input: string, defaultUnit: Unit = 'mm'): ParsedLength {
  const original = input;
  const text = input.trim().toLowerCase().replace(/\s+/g, ' ');
  if (!text) return { ok: false, original, reason: 'Введите размер' };
  const match = /^(\d+(?:[.,]\d+)?)\s*([a-zа-яё]+)?\.?$/.exec(text);
  if (!match) return { ok: false, original, reason: 'Не удалось распознать число и единицу' };
  const numberText = match[1].replace(',', '.');
  const unitText = match[2];
  let unit: Unit = defaultUnit;
  if (unitText) {
    const resolved = UNIT_ALIASES[unitText];
    if (!resolved) return { ok: false, original, reason: `Неизвестная единица «${unitText}»: укажите мм, см или м` };
    unit = resolved;
  }
  if (!unitText && numberText.includes('.')) {
    return { ok: false, original, reason: 'Дробное число без единицы неоднозначно: укажите мм, см или м' };
  }
  const mm = toMillimetres(numberText, unit);
  if (mm === null) return { ok: false, original, reason: 'Размер не равен целому числу миллиметров — уточните значение' };
  if (mm <= 0) return { ok: false, original, reason: 'Размер должен быть больше нуля' };
  return { ok: true, mm, unit, explicitUnit: Boolean(unitText), original, converted: unit !== 'mm' };
}

/** "450×370", "450x370 мм", "45 x 37 см" → two lengths with a shared trailing unit. */
export function parseDimensionsPair(input: string): { length: ParsedLength; width: ParsedLength } | null {
  const text = input.trim().toLowerCase();
  const match = /^(\d+(?:[.,]\d+)?)\s*([a-zа-яё]*)\s*[x×х*]\s*(\d+(?:[.,]\d+)?)\s*([a-zа-яё]*)$/.exec(text);
  if (!match) return null;
  const [, a, unitA, b, unitB] = match;
  const shared = unitB || unitA;
  return {
    length: parseLength(`${a}${unitA || shared ? ` ${unitA || shared}` : ''}`),
    width: parseLength(`${b}${shared ? ` ${shared}` : ''}`),
  };
}

export function describeConversion(parsed: ParsedLength): string | null {
  if (!parsed.ok || !parsed.converted) return null;
  return `${parsed.original.trim()} → ${parsed.mm} мм`;
}

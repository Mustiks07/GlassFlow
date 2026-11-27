/**
 * Display formatting. Money arrives as decimal strings from the backend and is
 * formatted by string manipulation only — no float arithmetic on commercial values.
 */

const NBSP = ' ';
const THIN = ' ';

function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, THIN);
}

/**
 * "1988.00" → "1 988,00 ₸"; "10000" → "10 000 ₸"; null → "нет данных".
 * Two decimals are shown when the value has a non-zero fraction or `fixed2` is set.
 */
export function formatMoney(value: string | null | undefined, options: { fixed2?: boolean; currency?: boolean } = {}): string {
  if (value === null || value === undefined || value === '') return 'нет данных';
  const match = /^(-)?(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!match) return value; // never silently coerce a malformed amount
  const [, sign = '', whole, fraction = ''] = match;
  let frac = fraction;
  if (options.fixed2 || /[1-9]/.test(fraction)) frac = (fraction + '00').slice(0, Math.max(2, fraction.replace(/0+$/, '').length));
  else frac = '';
  const body = `${sign}${groupThousands(whole.replace(/^0+(?=\d)/, ''))}${frac ? `,${frac}` : ''}`;
  return options.currency === false ? body : `${body}${NBSP}₸`;
}

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'нет данных';
  const sign = value < 0 ? '−' : '';
  return `${sign}${groupThousands(String(Math.abs(Math.trunc(value))))}`;
}

export function formatMm(value: number | null | undefined): string {
  return value === null || value === undefined ? 'нет данных' : `${formatInt(value)}${NBSP}мм`;
}

export function formatDims(dimensions: { length_mm: number; width_mm: number } | null | undefined): string {
  if (!dimensions) return 'нет данных';
  return `${formatInt(dimensions.length_mm)}${NBSP}×${NBSP}${formatInt(dimensions.width_mm)}${NBSP}мм`;
}

/** Integer mm² → "1,2345 м²" with exact integer math (no float rounding of the source). */
export function formatAreaM2(areaMm2: number | null | undefined, digits = 4): string {
  if (areaMm2 === null || areaMm2 === undefined) return 'нет данных';
  const negative = areaMm2 < 0;
  const abs = BigInt(Math.abs(Math.trunc(areaMm2)));
  const whole = abs / 1_000_000n;
  const rest = (abs % 1_000_000n).toString().padStart(6, '0').slice(0, digits);
  return `${negative ? '−' : ''}${groupThousands(whole.toString())}${digits ? `,${rest}` : ''}${NBSP}м²`;
}

/** A 0..1 ratio for display only (never used for business logic). */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'нет данных';
  return `${(value * 100).toFixed(digits).replace('.', ',')}${NBSP}%`;
}

export function formatSignedInt(value: number): string {
  if (value === 0) return '0';
  return `${value > 0 ? '+' : '−'}${groupThousands(String(Math.abs(value)))}`;
}

export function formatSignedMoney(value: string): string {
  if (value.startsWith('-')) return `−${formatMoney(value.slice(1))}`;
  if (/^0+(\.0+)?$/.test(value)) return formatMoney(value);
  return `+${formatMoney(value)}`;
}

const DATE_TIME = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Asia/Qyzylorda',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
});

/** UTC timestamps are displayed in Asia/Qyzylorda (spec §7). */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'не задано';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return DATE_TIME.format(date);
}

export function shortHash(value: string | null | undefined, length = 10): string {
  if (!value) return 'нет';
  return value.replace(/^sha256:/, '').slice(0, length);
}

export function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

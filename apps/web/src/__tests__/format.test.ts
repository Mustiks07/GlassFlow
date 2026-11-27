import { describe, expect, it } from 'vitest';
import { formatAreaM2, formatMoney, formatPercent } from '../lib/format';
import { parseDimensionsPair, parseLength } from '../lib/units';

const nb = (text: string) => text.replace(/[  ]/g, ' ');

describe('money formatting works on decimal strings, never floats', () => {
  it('formats thousands, comma decimals and currency', () => {
    expect(nb(formatMoney('1988.00', { fixed2: true }))).toBe('1 988,00 ₸');
    expect(nb(formatMoney('1991.76'))).toBe('1 991,76 ₸');
    expect(nb(formatMoney('10000'))).toBe('10 000 ₸');
    expect(nb(formatMoney('123456789012345678.5'))).toBe('123 456 789 012 345 678,50 ₸');
  });
  it('keeps unknown distinct from zero and refuses to coerce garbage', () => {
    expect(formatMoney(null)).toBe('нет данных');
    expect(nb(formatMoney('0'))).toBe('0 ₸');
    expect(formatMoney('12,5')).toBe('12,5');
  });
  it('formats integer mm² area exactly', () => {
    expect(nb(formatAreaM2(110_753_200))).toBe('110,7532 м²');
    expect(nb(formatAreaM2(171_100))).toBe('0,1711 м²');
  });
  it('formats ratios for display', () => {
    expect(nb(formatPercent(0.589523237, 4))).toBe('58,9523 %');
    expect(formatPercent(null)).toBe('нет данных');
  });
});

describe('dimension parsing: mm default, explicit cm/m converted, ambiguity rejected', () => {
  it('accepts mm and converts cm/m exactly', () => {
    expect(parseLength('450')).toMatchObject({ ok: true, mm: 450, converted: false });
    expect(parseLength('45 см')).toMatchObject({ ok: true, mm: 450, converted: true, unit: 'cm' });
    expect(parseLength('0,45 м')).toMatchObject({ ok: true, mm: 450, unit: 'm' });
    expect(parseLength('1.2 m')).toMatchObject({ ok: true, mm: 1200 });
    expect(parseLength('45,1 см')).toMatchObject({ ok: true, mm: 451 });
  });
  it('requires clarification instead of rounding', () => {
    expect(parseLength('45,55 см').ok).toBe(false);
    expect(parseLength('1.2').ok).toBe(false);
    expect(parseLength('450 дюймов').ok).toBe(false);
    expect(parseLength('0').ok).toBe(false);
    expect(parseLength('').ok).toBe(false);
  });
  it('parses pairs with a shared unit', () => {
    const pair = parseDimensionsPair('45 x 37 см');
    expect(pair?.length).toMatchObject({ ok: true, mm: 450 });
    expect(pair?.width).toMatchObject({ ok: true, mm: 370 });
    expect(parseDimensionsPair('450×370')?.width).toMatchObject({ ok: true, mm: 370 });
  });
});

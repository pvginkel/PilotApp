/**
 * A figure's words on the dashboard (F160.11), by the format the engine answers it in (the
 * catalogue's `Format`): dollars to the cent, tokens in thousands and millions, a count whole or to
 * two decimals where it is a median or a ratio, seconds as a duration, a share as a percentage; and
 * a multiple of a median under Relative. `–` where there is no figure.
 */

import type { components } from '@/lib/api/generated/types';

export type Format = components['schemas']['RowsResponseSchema.b67cf98.RowsMeasureSchema']['format'];

const NONE = '–';
const USD = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const COUNT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });
const WHOLE = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

/** A count whole, as the rows' n: "1,234". */
export function whole(value: number | null): string {
  return value === null ? NONE : WHOLE.format(value);
}

/** A share of a whole: "12%", "4.5%" under a tenth. */
export function percent(value: number | null): string {
  return value === null ? NONE : `${(value * 100).toFixed(Math.abs(value) < 0.1 ? 1 : 0)}%`;
}

function tokens(value: number): string {
  const size = Math.abs(value);
  if (size >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (size >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (size >= 1e4) return `${(value / 1e3).toFixed(0)}k`;
  if (size >= 1e3) return `${(value / 1e3).toFixed(1)}k`;
  return String(Math.round(value));
}

function duration(value: number): string {
  const seconds = Math.round(value);
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`;
  return `${Math.floor(seconds / 3600)}h ${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}m`;
}

/** A figure in its format's words. */
export function figure(format: Format, value: number | null): string {
  if (value === null) return NONE;
  switch (format) {
    case 'usd':
      return `$${USD.format(value)}`;
    case 'tokens':
      return tokens(value);
    case 'count':
      return COUNT.format(value);
    case 'seconds':
      return duration(value);
    case 'share':
      return percent(value);
    default: {
      const unknown: never = format;
      return unknown;
    }
  }
}

/** A multiple of a median, as Relative reads a figure: "12×", "1.5×", "0.25×". */
export function multiple(value: number | null): string {
  if (value === null) return NONE;
  return `${value >= 10 ? value.toFixed(0) : value >= 1 ? value.toFixed(1) : value.toFixed(2)}×`;
}

/**
 * The Table presentation's columns and its text (F163.3; the mockup's `table.js`, `columns` and
 * `text`): the By's rows under the All row; after the By's label each measure's figure and its n;
 * where the first measure sums or counts, a row's share of All; with a color, the first measure
 * that stacks split over the color's values, a column each. Copy and CSV take every row of the
 * answer as its figures, the All row first, and where the By's values have a time, the instant,
 * after the label: tab-separated for the clipboard, comma-separated for a file. Pure, with no DOM.
 */

import { figure, percent, whole } from './figures';
import type { Rows } from './rows-layout';

/** A row of the answer, the All row among them. */
type Line = Pick<Rows['all'], 'values' | 'n' | 'split'>;

export interface Column {
  kind: 'measure' | 'n' | 'share' | 'split';
  /** Its heading. */
  label: string;
  title: string | null;
  /** A split's color value's fill, as the chart draws it. */
  swatch: string | null;
  /** Its figure on a line; none where the line has none. */
  value: (line: Line) => number | null;
  words: (value: number | null) => string;
}

/** The categorical palette's size (`--series-0` to `--series-19`, dashboard.css). */
const SERIES = 20;

const SUMS = new Set(['sum', 'count']);

/** The columns after the By's label. */
export function columnsOf(rows: Rows): Column[] {
  const columns: Column[] = [];
  rows.measures.forEach((measure, j) => {
    columns.push({ kind: 'measure', label: measure.label, title: null, swatch: null, value: (line) => line.values[j] ?? null, words: (value) => figure(measure.format, value) });
    columns.push({ kind: 'n', label: 'n', title: `The items behind ${measure.label}`, swatch: null, value: (line) => line.n[j] ?? null, words: whole });
  });
  const first = rows.measures[0];
  const total = rows.all.values[0] ?? null;
  if (first !== undefined && first.aggregate !== null && SUMS.has(first.aggregate)) {
    columns.push({ kind: 'share', label: 'Share', title: `Each row’s ${first.label} as a share of All`, swatch: null, value: (line) => (total ? (line.values[0] ?? 0) / total : null), words: percent });
  }
  const stacked = rows.measures.findIndex((measure) => measure.stacks);
  if (stacked >= 0 && rows.color !== null) {
    const { label, format } = rows.measures[stacked];
    for (const [k, value] of rows.color.values.entries()) {
      const name = value.label ?? String(value.key);
      columns.push({
        kind: 'split',
        label: name,
        title: `${rows.color.label}: ${name} (${label})`,
        swatch: value.others > 0 ? 'var(--series-other)' : `var(--series-${k % SERIES})`,
        value: (line) => line.split?.[stacked]?.[k] ?? null,
        words: (amount) => (amount === null ? '' : figure(format, amount)),
      });
    }
  }
  return columns;
}

/** Every row of the answer as text, its headings first, then the All row: separated by tabs, or by commas, quoted where it must be. */
export function tableText(rows: Rows, separator: '\t' | ','): string {
  const columns = columnsOf(rows);
  const timed = rows.rows.some((row) => row.at !== null);
  const cell = (text: string) =>
    separator === '\t' ? text.replace(/[\t\r\n]+/g, ' ') : /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  const line = (label: string, at: string | null, figures: Line) =>
    [label, ...(timed ? [at ?? ''] : []), ...columns.map((column) => String(column.value(figures) ?? ''))].map(cell).join(separator);
  return [
    [rows.by.label, ...(timed ? ['At'] : []), ...columns.map((column) => column.label)].map(cell).join(separator),
    line('All', null, rows.all),
    ...rows.rows.map((row) => line(row.label ?? String(row.key), row.at, row)),
  ].join('\n');
}

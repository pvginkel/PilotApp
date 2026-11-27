/**
 * The Rows presentation's geometry (F163.3, F164.1), the mockup's `rows.js` carried over with no
 * DOM in it: a row per value of the By, the first 40 in the answer's order (or up to 1,000 with
 * Show all) under the All row; a column per measure on its own scale, a figure that stacks split
 * by the color; the n of the first measure per row; "–" where a row has no figure; the peers'
 * median as a tick per column. Under Relative every figure with a median is a multiple of it, the
 * columns on one scale. A row's label is cut to its column (`clip.ts`); a By whose values have a
 * time (a Pilot session, a Pilot turn, a conversation, a Call) gives each row a second line, its
 * time in the engine's zone.
 *
 * Its coordinates are the chart's own, under the headings' row, which the page draws over the
 * columns from `head`: each measure's heading its name (`measures.ts`), the arrow of the sort
 * after it where the rows are sorted by its column, cut to its column at rest and short of its
 * controls, the menu's sign and the ×, under the pointer.
 */

import type { components } from '@/lib/api/generated/types';
import { clip, type Measure } from './clip';
import { dayTime } from './dates';
import { figure, multiple, percent, whole, type Format } from './figures';

export type Rows = components['schemas']['RowsResponseSchema.b67cf98'];
type Answered = Rows['measures'][number];
type Sort = Rows['sort'];

/** The rows drawn until Show all. */
const MAX_ROWS = 40;
/** The rows Show all draws at most. */
export const SHOW_ALL = 1000;

/** The categorical palette's size (`--series-0` to `--series-19`, dashboard.css). */
const SERIES = 20;
/** A bar no color splits, and the color's values folded into one. */
const UNSPLIT = 'var(--series-other)';

const HEAD_HEIGHT = 22;
/** A heading's text: its size and weight (dashboard.css, `.rowheads`). */
const HEAD_SIZE = 11.5;
const HEAD_WEIGHT = 600;
/** The arrow's gap before it, and the controls' room: the menu's sign, with the × after it where a heading has one (dashboard.css, `.dash-mhead`). */
const ARROW_GAP = 4;
const MENU = 21;
const REMOVE = 20;
const N_WIDTH = 52;
const ROW = 26;
/** A row with its time on a second line. */
const ROW_TWO_LINES = 38;
const BAR = 15;

interface Segment {
  x: number;
  width: number;
  fill: string;
}

interface Cell {
  segments: Segment[];
  /** The part a mark holds of the row's figure, a line under its bar. */
  mark: { x: number; width: number } | null;
  text: { x: number; words: string };
}

interface RowLine {
  /** The By's value as the answer gives it, `~` for none. */
  key: string;
  y: number;
  /** The baselines of its first line and of its second, and its bars' top. */
  first: number;
  second: number;
  barY: number;
  marked: boolean;
  /** The label as drawn, cut to its room, and whole. */
  label: string;
  whole: string;
  /** Its time, the second line; null for a By whose values have none. */
  at: string | null;
  n: string;
  cells: Cell[];
}

/** A measure's heading over its column. */
interface Heading {
  x: number;
  width: number;
  /** Its name whole; cut to the column at rest, and short of its controls under the pointer. */
  name: string;
  rest: string;
  hover: string;
  /** The way the rows are sorted by its column; none where they are not. */
  sorted: Sort['direction'] | null;
}

interface Median {
  x: number;
  labelX: number;
  words: string;
  title: string;
}

export interface Layout {
  width: number;
  /** The chart's height under the headings. */
  height: number;
  rowHeight: number;
  barHeight: number;
  /** The headings' row: the By's at the left, n's right edge, each measure's column. */
  head: {
    height: number;
    by: { words: string; room: number };
    nRight: number;
    columns: Heading[];
  };
  /** The columns' rules. */
  rules: number[];
  all: { y: number; height: number; baseline: number; words: string; n: string; values: { x: number; words: string }[] };
  /** Under the All row, the line over the rows. */
  top: number;
  bottom: number;
  rows: RowLine[];
  medians: Median[];
  /** The rows drawn, and the By's rows in all. */
  shown: number;
  total: number;
  nX: number;
}

interface Column {
  measure: Answered;
  j: number;
  x0: number;
  /** What a figure is divided by: its median under Relative, else 1. */
  by: number;
  relative: boolean;
  median: number | null;
  max: number;
  words: (value: number | null) => string;
}

/** The color's value at `index` in its order, folded or its own. */
const fill = (others: number, index: number) => (others > 0 ? UNSPLIT : `var(--series-${index % SERIES})`);

interface Options {
  width: number;
  relative: boolean;
  /** Show all: up to SHOW_ALL rows. */
  all: boolean;
  measure: Measure;
  /** Each measure's name, in the answer's order. */
  names: readonly string[];
}

/** The rows of `answer` laid out at `width`. */
export function layOut(answer: Rows, { width: wide, relative, all, measure, names }: Options): Layout {
  const measures = answer.measures;
  const rows = answer.rows.slice(0, all ? SHOW_ALL : MAX_ROWS);
  const one = measures.length === 1;
  const width = Math.max(wide, 320);
  const labelWidth = Math.min(280, Math.round(width * (one ? 0.32 : 0.22)));
  // n's right edge, 6 px short of the first column's rule.
  const nX = labelWidth + N_WIDTH - 14;
  const columnWidth = (width - labelWidth - N_WIDTH) / measures.length;
  const valueWidth = one ? 110 : 74;
  const barWidth = Math.max(columnWidth - valueWidth - 14, 8);
  const timed = rows.some((row) => row.at !== null);
  const rowHeight = timed ? ROW_TWO_LINES : ROW;
  const allY = 2;
  const top = allY + ROW + 4;
  const bottom = top + rows.length * rowHeight;
  const colorValues = answer.color?.values ?? [];

  const columns: Column[] = measures.map((answered, j) => {
    const median = answered.median;
    const isRelative = relative && median !== null && median !== 0;
    const by = isRelative ? median : 1;
    const format: Format = answered.format;
    return {
      measure: answered,
      j,
      x0: labelWidth + N_WIDTH + j * columnWidth,
      by,
      relative: isRelative,
      median: median === null ? null : median / by,
      max: Math.max(...rows.map((row) => (row.values[j] ?? 0) / by), median === null ? 0 : median / by, 1e-12),
      words: isRelative ? multiple : (value) => figure(format, value),
    };
  });
  if (relative) {
    const shared = Math.max(...columns.filter((column) => column.relative).map((column) => column.max), 1);
    for (const column of columns) if (column.relative) column.max = shared;
  }

  const allValues = answer.all.values;
  const total = allValues[0] ?? null;
  const lines: RowLine[] = rows.map((row, i) => {
    const y = top + i * rowHeight;
    const name = `${row.marked ? '◇ ' : ''}${row.label ?? String(row.key)}`;
    const n = whole(row.n[0] ?? null);
    const end = Math.min(labelWidth - 6, nX - 8 - measure(n, 12, 400));
    const cells = columns.map((column): Cell => {
      const raw = row.values[column.j];
      const value = raw === null ? null : raw / column.by;
      const split = row.split?.[column.j];
      const parts = split
        ? colorValues
            .map((colorValue, index) => ({ fill: fill(colorValue.others, index), amount: (split[index] ?? 0) / column.by }))
            .filter((part) => part.amount > 0)
        : [];
      const segments: Segment[] = [];
      let mark: Cell['mark'] = null;
      if (value !== null) {
        let x = column.x0;
        for (const part of parts.length > 0 ? parts : [{ fill: UNSPLIT, amount: value }]) {
          if (part.amount <= 0) continue;
          const segmentWidth = (part.amount / column.max) * barWidth;
          segments.push({ x, width: Math.max(segmentWidth, 0.5), fill: part.fill });
          x += segmentWidth;
        }
        const marked = row.marks?.[column.j];
        if (marked) mark = { x: column.x0, width: Math.max((marked / column.by / column.max) * barWidth, 1) };
      }
      const share =
        one && !column.relative && value !== null && total && (column.measure.aggregate === 'sum' || column.measure.aggregate === 'count')
          ? ` · ${percent(value / total)}`
          : '';
      return {
        segments,
        mark,
        text: { x: column.x0 + (value ? Math.min(value / column.max, 1) * barWidth : 0) + 6, words: `${column.words(value)}${share}` },
      };
    });
    const barY = y + (rowHeight - 2 - BAR) / 2;
    return {
      key: row.key === null ? '~' : String(row.key),
      y,
      first: timed ? y + 15 : y + rowHeight / 2 + 3,
      second: y + 29,
      barY,
      marked: row.marked,
      label: clip(name, end - 6, measure),
      whole: name,
      at: row.at === null ? null : dayTime(row.at, answer.zone),
      n,
      cells,
    };
  });

  const focused = answer.rows.some((row) => row.focus);
  const peers = focused ? "the peers' median: the rows less the focus's" : 'the median of the rows';
  const medians: Median[] = [];
  for (const column of columns) {
    if (column.median === null || column.measure.median === null) continue;
    const x = column.x0 + Math.min(column.median / column.max, 1) * barWidth;
    const words = column.relative ? `1× = ${figure(column.measure.format, column.measure.median)}` : `median ${column.words(column.median)}`;
    const half = measure(words, 10.5, 400) / 2;
    const counted = answer.rows.filter((row) => !row.focus && row.values[column.j] !== null).length;
    medians.push({
      x,
      labelX: Math.max(column.x0 - 2 + half, Math.min(x, column.x0 + columnWidth - 12 - half)),
      words,
      title: `${peers}, ${whole(counted)} with a figure`,
    });
  }

  return {
    width,
    height: bottom + 34,
    rowHeight,
    barHeight: BAR,
    head: {
      height: HEAD_HEIGHT,
      by: { words: answer.by.label, room: labelWidth - 12 },
      nRight: width - nX,
      columns: columns.map((column): Heading => {
        const name = names[column.j];
        const sorted = answer.sort.column === column.measure.key ? answer.sort.direction : null;
        const room = columnWidth - 12 - (sorted === null ? 0 : ARROW_GAP + measure(sorted === 'asc' ? '▲' : '▼', HEAD_SIZE * 0.85, HEAD_WEIGHT));
        const controls = MENU + (measures.length > 1 ? REMOVE : 0);
        return {
          x: column.x0,
          width: columnWidth - 12,
          name,
          rest: clip(name, room, measure, HEAD_SIZE, HEAD_WEIGHT),
          hover: clip(name, room - controls, measure, HEAD_SIZE, HEAD_WEIGHT),
          sorted,
        };
      }),
    },
    rules: columns.map((column) => column.x0 - 8),
    all: {
      y: allY,
      height: ROW - 2,
      baseline: allY + ROW / 2 + 3,
      words: `All · ${whole(answer.total_rows)}${relative ? ' (absolute)' : ''}`,
      n: whole(answer.all.n[0] ?? null),
      values: columns.map((column) => ({ x: column.x0, words: figure(column.measure.format, allValues[column.j] ?? null) })),
    },
    top,
    bottom,
    rows: lines,
    medians,
    shown: rows.length,
    total: answer.total_rows,
    nX,
  };
}

/**
 * What a view draws, in words (F161.4), built on the page, since no route describes a view: what
 * it presents, over what time and which measures, "By Project · All time · Cost, Tokens", a
 * series in order its order dimension's label, which says the order; and a dimension's label,
 * which names a tab by its By (F161.2). A view's time reads in the same words collapsed in the
 * time picker (F162.2): "Quota week 46" for this, the last and one picked quota week, a range's
 * label for the others, a range between two times its days, "7 Nov – 13 Nov". Each word is the
 * catalogue's, a part of it that has not come yet reading its key. Pure, with no DOM.
 */

import type { Catalogue } from './queries';
import type { ViewState } from './state';

/** The catalogue's parts a view is worded from, each none until it has come. */
export interface Words {
  dimensions: Catalogue | undefined;
  measures: Catalogue | undefined;
  time: Catalogue | undefined;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** A dimension's label, of the catalogue's `dimensions` part; its key until that has come. */
export const dimensionLabel = (dimensions: Catalogue | undefined, key: string) =>
  dimensions?.dimensions?.find((dimension) => dimension.key === key)?.label ?? key;

function presentationWords(state: ViewState, words: Words): string {
  const by = dimensionLabel(words.dimensions, state.by);
  switch (state.presentation) {
    case 'rows':
      return `By ${by}`;
    case 'table':
      return `Table by ${by}`;
    case 'lanes':
      return `Lanes by ${by}`;
    case 'time':
      return state.axis === null ? 'Over time' : `Over time, by ${dimensionLabel(words.dimensions, state.axis).toLowerCase()}`;
    case 'order': {
      const order = state.axis ?? words.dimensions?.dimensions?.find((dimension) => dimension.group === 'order' && dimension.base === state.by)?.key;
      return order === undefined ? by : dimensionLabel(words.dimensions, order);
    }
    default: {
      const unknown: never = state.presentation;
      return unknown;
    }
  }
}

/** A bound as a state writes it, a date or a time of day in the dashboard's zone: "7 Nov", "7 Nov 09:52". */
function boundWords(bound: string, year: number): string {
  const [day, time] = bound.split(/[T ]/);
  const [y, m, d] = day.split('-').map(Number);
  return `${d} ${MONTHS[m - 1]}${y === year ? '' : ` ${y}`}${time === undefined ? '' : ` ${time.slice(0, 5)}`}`;
}

/** A quota week, by the instant it starts: its number, or for one cut short with no Thursday in it, its first day: "46", "of 1 Nov". */
export function weekWords(start: string, words: Words): string {
  const week = words.time?.quota_weeks?.find((each) => Date.parse(each.starts_at) === Date.parse(start));
  if (week?.week != null) return String(week.week);
  const day = week?.starts_on ?? start.slice(0, 10);
  return `of ${boundWords(day, new Date().getFullYear())}`;
}

/** The ranges that are one quota week, by their keys, and which of the weeks newest first each is. */
const WEEK_RANGES: Record<string, number> = { qw: 0, lqw: 1 };

/** A view's time: a range's label, this and the last quota week by its number; quota weeks by their numbers; a range between two times its days. */
export function timeWords(time: ViewState['time'], words: Words): string {
  switch (time.kind) {
    case 'preset': {
      const week = time.key in WEEK_RANGES ? words.time?.quota_weeks?.[WEEK_RANGES[time.key]] : undefined;
      if (week !== undefined) return `Quota week ${weekWords(week.starts_at, words)}`;
      return words.time?.ranges?.find((range) => range.key === time.key)?.label ?? time.key;
    }
    case 'weeks':
      return `${time.starts.length === 1 ? 'Quota week' : 'Quota weeks'} ${time.starts.map((start) => weekWords(start, words)).join(', ')}`;
    case 'between': {
      const year = new Date().getFullYear();
      if (time.start === null) return `Until ${boundWords(time.end!, year)}`;
      if (time.end === null) return `From ${boundWords(time.start, year)}`;
      if (time.start === time.end && !/[T ]/.test(time.start)) return boundWords(time.start, year);
      return `${boundWords(time.start, year)} – ${boundWords(time.end, year)}`;
    }
    default: {
      const unknown: never = time;
      return unknown;
    }
  }
}

/** A measure in a line of them: its figure's label, its aggregate after it where it is not the figure's own; a ratio's name. */
export function measureWords(measure: ViewState['measures'][number], words: Words): string {
  const part = words.measures;
  switch (measure.kind) {
    case 'simple': {
      const figure = part?.figures?.find((each) => each.key === measure.figure);
      if (figure === undefined) return measure.figure;
      if (measure.aggregate === figure.aggregate) return figure.label;
      const aggregate = part?.aggregates?.find((each) => each.key === measure.aggregate)?.label ?? measure.aggregate;
      return `${figure.label} (${aggregate.toLowerCase()})`;
    }
    case 'ratio':
      return part?.ratios?.find((ratio) => ratio.key === measure.key)?.label ?? measure.key;
    case 'written':
      return measure.name;
    default: {
      const unknown: never = measure;
      return unknown;
    }
  }
}

/** What `state` draws, in words: its presentation, its time, its measures. */
export function describe(state: ViewState, words: Words): string {
  return [presentationWords(state, words), timeWords(state.time, words), state.measures.map((measure) => measureWords(measure, words)).join(', ')].join(' · ');
}

/**
 * The time picker's bounds and words (F162.2; the mockup's `time.js` and `dates.js`). A bound is a
 * wall time in the dashboard's zone, a day with a time of day or the day whole, as a range of a
 * state writes it (`c,<start>,<end>`, `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`); an end that is a day
 * holds it whole, as the server reads it. A field takes a bound typed day first, "12 Nov 2026",
 * "12-11-2026", "12/11", or ISO, "2026-11-12", each with a time of day after it or none, a day with
 * no year this year's. The quota weeks are the catalogue's, each by the instant it starts, never
 * built from an ISO week as the mockup's are. Pure, with no DOM.
 */

import { MONTHS, wall, type Wall } from './dates';

/** A bound of a range, in the dashboard's zone. */
export interface Bound {
  year: number;
  month: number;
  day: number;
  /** Its time of day; none for the day whole. */
  time: { hour: number; minute: number } | null;
}

type Day = Pick<Bound, 'year' | 'month' | 'day'>;

/** A span of the time a view reads, as the rows' answer gives it: its end exclusive, none on a side open. */
interface Span {
  start: string | null;
  end: string | null;
}

/** The weekdays' short names, Monday first. */
export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

/** The months' names a field reads beyond the English ones: the Dutch spellings the short English names miss. */
const OTHER_MONTHS: Record<string, number> = { mrt: 3, mei: 5, okt: 10 };

const DAY = 86_400_000;

const pad = (value: number) => String(value).padStart(2, '0');

/** A day's number, counted from 1 January 1970: to step from one day to the next and to compare two. */
export const dayNumber = (day: Day) => Math.round(Date.UTC(day.year, day.month - 1, day.day) / DAY);

/** The day numbered `n`, whole. */
export function dayOf(n: number): Bound {
  const at = new Date(n * DAY);
  return { year: at.getUTCFullYear(), month: at.getUTCMonth() + 1, day: at.getUTCDate(), time: null };
}

/** A day's weekday, 0 Monday to 6 Sunday. */
export const weekdayOf = (day: Day) => (new Date(Date.UTC(day.year, day.month - 1, day.day)).getUTCDay() + 6) % 7;

/** The days `month` of `year` holds. */
export const daysIn = (year: number, month: number) => new Date(Date.UTC(year, month, 0)).getUTCDate();

/** A month's name and its year: "November 2026". */
export const monthWords = (year: number, month: number) => `${MONTH_NAMES[month - 1]} ${year}`;

/** A day with its weekday and its year, as a calendar's day is named: "Thu 12 Nov 2026". */
export const dayName = (day: Day) => `${WEEKDAYS[weekdayOf(day)]} ${day.day} ${MONTHS[day.month - 1]} ${day.year}`;

/** A bound as a field shows it, its year always: "12 Nov 2026", "12 Nov 2026 11:00". */
export function boundText(bound: Bound): string {
  const day = `${bound.day} ${MONTHS[bound.month - 1]} ${bound.year}`;
  return bound.time === null ? day : `${day} ${pad(bound.time.hour)}:${pad(bound.time.minute)}`;
}

function monthOf(name: string): number {
  const key = name.slice(0, 3).toLowerCase();
  const index = MONTHS.findIndex((month) => month.toLowerCase() === key);
  return index >= 0 ? index + 1 : (OTHER_MONTHS[key] ?? 0);
}

/** What a field holds: none where it is empty, undefined where it reads as no bound; a day with no year `year`'s. */
export function parseBound(text: string, year: number): Bound | null | undefined {
  const typed = text.trim().replace(/\s+/g, ' ');
  if (typed === '') return null;
  const clock = /[ T,]+(\d{1,2})[:.](\d{2})$/.exec(typed);
  const date = (clock === null ? typed : typed.slice(0, clock.index)).trim();
  let read: [number, number, number];
  let match: RegExpExecArray | null;
  if ((match = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(date)) !== null) read = [+match[1], +match[2], +match[3]];
  else if ((match = /^(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2}|\d{4}))?$/.exec(date)) !== null) read = [match[3] === undefined ? year : +match[3], +match[2], +match[1]];
  else if ((match = /^(\d{1,2}) ?([A-Za-z]{3,})\.?(?: (\d{2}|\d{4}))?$/.exec(date)) !== null) read = [match[3] === undefined ? year : +match[3], monthOf(match[2]), +match[1]];
  else return undefined;
  const [y, month, day] = read;
  const full = y < 100 ? y + 2000 : y;
  const real = new Date(Date.UTC(full, month - 1, day));
  if (month < 1 || real.getUTCFullYear() !== full || real.getUTCMonth() !== month - 1 || real.getUTCDate() !== day) return undefined;
  if (clock === null) return { year: full, month, day, time: null };
  const hour = +clock[1];
  const minute = +clock[2];
  if (hour > 23 || minute > 59) return undefined;
  return { year: full, month, day, time: { hour, minute } };
}

/** A bound as a state writes it: "2026-11-12", "2026-11-12T11:00". */
export function boundKey(bound: Bound): string {
  const day = `${bound.year}-${pad(bound.month)}-${pad(bound.day)}`;
  return bound.time === null ? day : `${day}T${pad(bound.time.hour)}:${pad(bound.time.minute)}`;
}

/** A state's bound, to the minute. */
export function readBound(written: string): Bound {
  const [, y, month, day, hour, minute] = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(written)!;
  return { year: +y, month: +month, day: +day, time: hour === undefined ? null : { hour: +hour, minute: +minute } };
}

/** An instant as a bound in `zone`, to the minute. */
export function boundAt(at: Date, zone: string): Bound {
  const shown = wall(at, zone);
  return { year: shown.year, month: shown.month, day: shown.day, time: { hour: shown.hour, minute: shown.minute } };
}

const minuteOf = (bound: Bound) => dayNumber(bound) * 1440 + (bound.time === null ? 0 : bound.time.hour * 60 + bound.time.minute);

/** Whether the range from `start` to `end` holds a moment, an end that is a day holding it whole: the server refuses one that does not. */
export const inOrder = (start: Bound, end: Bound) => minuteOf(start) < (end.time === null ? (dayNumber(end) + 1) * 1440 : minuteOf(end));

/** The last day an end takes in: its own, or the day before where it is that day's first minute. */
export const lastDayOf = (end: Bound) => dayNumber(end) - (end.time !== null && end.time.hour === 0 && end.time.minute === 0 ? 1 : 0);

const exact = (shown: Wall) => `${dayName(shown)} ${pad(shown.hour)}:${pad(shown.minute)}`;

/**
 * The time a view reads, exactly, the time's title: each span's first and last moment in `zone`,
 * two that touch one span, an open start "The start"; an end that is not a range's own (`custom`)
 * and is past `now` reads "now". None for a window that holds no time.
 */
export function exactWords(window: readonly Span[] | null, zone: string, custom: boolean, now: Date): string | null {
  if (window === null) return 'All time';
  const spans: [number | null, number | null][] = [];
  for (const span of window) {
    const start = span.start === null ? null : Date.parse(span.start);
    const end = span.end === null ? null : Date.parse(span.end);
    const last = spans.at(-1);
    if (last !== undefined && last[1] !== null && last[1] === start) last[1] = end;
    else spans.push([start, end]);
  }
  if (spans.length === 0) return null;
  const at = (moment: number) => exact(wall(new Date(moment), zone));
  const words = spans.map(([start, end]) => `${start === null ? 'The start' : at(start)} – ${end === null || (!custom && end >= now.getTime()) ? 'now' : at(end)}`);
  return `${words.join(', ')}, ${zone}`;
}

/** A quota week's span exactly, the week's title in the list: "Thu 12 Nov 2026 11:00 – Thu 19 Nov 2026 11:00". */
export const spanWords = (startsAt: string, endsAt: string, zone: string) => `${exact(wall(new Date(startsAt), zone))} – ${exact(wall(new Date(endsAt), zone))}`;

/** An instant's day in `zone`, the year where it is not `now`'s there: "12 Nov", "12 Nov 2025". */
export function dayWords(at: string, zone: string, now: Date = new Date()): string {
  const shown = wall(new Date(at), zone);
  return `${shown.day} ${MONTHS[shown.month - 1]}${shown.year === wall(now, zone).year ? '' : ` ${shown.year}`}`;
}

/** An instant's weekday, day and time of day in `zone`, the year where it is not `now`'s there: "Thu 12 Nov 11:00". */
export function startedWords(at: string, zone: string, now: Date = new Date()): string {
  const shown = wall(new Date(at), zone);
  return `${WEEKDAYS[weekdayOf(shown)]} ${dayWords(at, zone, now)} ${pad(shown.hour)}:${pad(shown.minute)}`;
}

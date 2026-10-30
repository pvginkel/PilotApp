/**
 * A time's words as every screen gives them (F114), in the browser's time zone. The record and the
 * API hold it in UTC.
 */

const FORMATS = {
  /** The day and the month, as a finished project's tab shows them. */
  day: new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }),
  /** The hour and the minute, as the timeline shows them under its date dividers. */
  clock: new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' }),
  /** The day, the month, the hour and the minute: a time of an earlier day where the clock alone shows today's. */
  dated: new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }),
  /** The date and the time, as a finished timeline's end divider shows them. */
  stamp: new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' }),
  /** The whole stamp, a time's tooltip. */
  full: new Intl.DateTimeFormat('en-GB', { dateStyle: 'full', timeStyle: 'long' }),
};

export type TimeFormat = keyof typeof FORMATS;

export function formatTime(at: string, format: TimeFormat): string {
  return FORMATS[format].format(new Date(at));
}

/** The clock alone for a time on the viewer's `today` (`useToday()`), the date with it for an earlier day's. */
export function clockFormat(at: string, today: string): 'clock' | 'dated' {
  return new Date(at).toDateString() === today ? 'clock' : 'dated';
}

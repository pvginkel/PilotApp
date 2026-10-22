/**
 * A time as every screen shows it (F114): in the browser's time zone, the full stamp as its
 * tooltip. The record and the API hold it in UTC.
 */

const FORMATS = {
  /** The day and the month, as a finished project's tab shows them. */
  day: new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }),
  /** The hour and the minute, as the timeline shows them under its date dividers. */
  clock: new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' }),
};
const FULL_STAMP = new Intl.DateTimeFormat('en-GB', { dateStyle: 'full', timeStyle: 'long' });

interface TimeProps {
  at: string;
  format?: keyof typeof FORMATS;
  testId?: string;
}

export function Time({ at, format = 'day', testId }: TimeProps) {
  const date = new Date(at);
  return (
    <time dateTime={at} title={FULL_STAMP.format(date)} data-testid={testId}>
      {FORMATS[format].format(date)}
    </time>
  );
}

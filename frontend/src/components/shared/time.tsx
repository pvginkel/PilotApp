/**
 * A time as every screen shows it (F114): in the browser's time zone, the full stamp as its
 * tooltip. The record and the API hold it in UTC.
 */

const DAY = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' });
const FULL_STAMP = new Intl.DateTimeFormat('en-GB', { dateStyle: 'full', timeStyle: 'long' });

/** The day and the month, as a finished project's tab shows them. */
export function Time({ at }: { at: string }) {
  const date = new Date(at);
  return (
    <time dateTime={at} title={FULL_STAMP.format(date)}>
      {DAY.format(date)}
    </time>
  );
}

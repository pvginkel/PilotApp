/**
 * The dashboard's dates (F160.11): day first, the month's short name, a 24-hour clock, "7 Nov
 * 09:52", the year after the month where it is not this one, "7 Nov 2025 09:52"; always in the
 * engine's zone, a server setting each answer names (`zone`), never the browser's. The month's
 * names are the page's own, so that no locale's spelling ("Sept") reaches the screen.
 */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

interface Wall {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

const formats = new Map<string, Intl.DateTimeFormat>();

/** An instant's wall time in `zone`. */
function wall(at: Date, zone: string): Wall {
  let format = formats.get(zone);
  if (format === undefined) {
    format = new Intl.DateTimeFormat('en-GB', {
      timeZone: zone,
      hourCycle: 'h23',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
    });
    formats.set(zone, format);
  }
  const parts = Object.fromEntries(format.formatToParts(at).map((part) => [part.type, part.value]));
  return { year: +parts.year, month: +parts.month, day: +parts.day, hour: +parts.hour, minute: +parts.minute };
}

const pad = (value: number) => String(value).padStart(2, '0');

/** `at`, an instant as the API writes it, as its day and its time of day in `zone`, the year shown where it is not `now`'s there. */
export function dayTime(at: string, zone: string, now: Date = new Date()): string {
  const shown = wall(new Date(at), zone);
  const year = shown.year === wall(now, zone).year ? '' : ` ${shown.year}`;
  return `${shown.day} ${MONTHS[shown.month - 1]}${year} ${pad(shown.hour)}:${pad(shown.minute)}`;
}

const DAY = new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });

/** A day as the chat's date dividers and *load more* name it, in the browser's time zone: "Monday 26 October". */
export const day = (iso: string): string => DAY.format(new Date(iso));

/** The day a time falls on, in the browser's time zone, to compare. */
export const dayKey = (iso: string): string => new Date(iso).toDateString();

/** Durations as the working cue shows them: "4 s", "1 min 5 s". */
export function duration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return s % 60 ? `${m} min ${s % 60} s` : `${m} min`;
}

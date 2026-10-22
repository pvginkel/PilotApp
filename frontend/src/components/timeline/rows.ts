/**
 * The timeline's rows (F9): a date divider per day in the browser's time zone, and a step divider
 * where the step changes, its label the title of the plan task the items under it serve. An item
 * serving none starts no divider and ends no step: the next item of the same step starts none.
 */

import type { TimelineItem } from '@/hooks/use-timeline';

export type Row =
  | { type: 'day'; key: string; label: string }
  | { type: 'step'; key: string; title: string }
  | { type: 'item'; key: string; item: TimelineItem };

const DAY = new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });

export function rowsOf(items: TimelineItem[]): Row[] {
  const rows: Row[] = [];
  let day: string | null = null;
  let step: string | null = null;
  for (const item of items) {
    const date = new Date(item.created_at);
    if (date.toDateString() !== day) {
      day = date.toDateString();
      rows.push({ type: 'day', key: `day:${item.id}`, label: DAY.format(date) });
    }
    if (item.step !== null && item.step.id !== step) {
      step = item.step.id;
      rows.push({ type: 'step', key: `step:${item.id}`, title: item.step.title });
    }
    rows.push({ type: 'item', key: item.id, item });
  }
  return rows;
}

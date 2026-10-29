/**
 * The timeline's rows (F9): a date divider per day in the browser's time zone, and a step divider
 * where the step changes, its label the title of the plan task the items under it serve. An item
 * serving none starts no divider and ends no step: the next item of the same step starts none. No
 * divider falls between consecutive work items: a run of them stands under its last member's
 * date and step dividers, placed before the run (F9.1). The ready line stands right under the item
 * the timeline names for it, the setup's (D083).
 */

import type { TimelineItem } from '@/hooks/use-timeline';

export type Row =
  | { type: 'day'; key: string; label: string }
  | { type: 'step'; key: string; title: string }
  | { type: 'item'; key: string; item: TimelineItem }
  | { type: 'ready'; key: string };

const DAY = new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });

export function rowsOf(items: TimelineItem[], readyAfter: string | null = null): Row[] {
  const rows: Row[] = [];
  let day: string | null = null;
  let step: string | null = null;
  for (const run of runsOf(items)) {
    const last = run[run.length - 1];
    // Keyed by the run's first member, which a run that grows keeps.
    const first = run[0].id;
    const date = new Date(last.created_at);
    if (date.toDateString() !== day) {
      day = date.toDateString();
      rows.push({ type: 'day', key: `day:${first}`, label: DAY.format(date) });
    }
    if (last.step !== null && last.step.id !== step) {
      step = last.step.id;
      rows.push({ type: 'step', key: `step:${first}`, title: last.step.title });
    }
    for (const item of run) {
      rows.push({ type: 'item', key: item.id, item });
      if (item.id === readyAfter) rows.push({ type: 'ready', key: `ready:${item.id}` });
    }
  }
  return rows;
}

/** The items in their order, each alone but consecutive work items, which are one run. */
function runsOf(items: TimelineItem[]): TimelineItem[][] {
  const runs: TimelineItem[][] = [];
  for (const item of items) {
    const run = runs.at(-1);
    if (item.kind === 'work' && run?.[0].kind === 'work') run.push(item);
    else runs.push([item]);
  }
  return runs;
}

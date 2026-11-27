/**
 * A By's sort kept within a tab (F161.6; the mockup's `main.js`, `sortOf` and `forgetGoneSorts`,
 * and `heads.js`): the tab remembers the sort of what each of its states asks (`asked` in
 * `scope.ts`: the By, or a series' axis), so that a move that lands on a By, a drill down or a step
 * back up the drill path or a By picked, finds the sort it had there. The first a tab remembers for
 * a By is the sort of the state it opened with, a link's or a saved view's; a sort the person picks
 * is remembered for what the view asks. A sort on a measure the view no longer shows is forgotten,
 * the one the tab opened with among them, the server refusing a sort on a column the view lacks
 * (`backend/app/dashboard/reading.py`, "is no column of the view"); a measure changed in place, its
 * aggregate or its grain, takes the sorts on it along. Pure, with no DOM.
 */

import type { Catalogue } from './queries';
import { asked } from './scope';
import { measureKey, type ViewState } from './state';

export type Sort = NonNullable<ViewState['sort']>;

/** The sorts a tab remembers, by what was asked; none where the one it opened with is forgotten. */
export type Sorts = Readonly<Record<string, Sort | null>>;

/** The columns a sort names besides the view's measures (`backend/app/dashboard/state.py`, `OWN_COLUMNS`). */
const OWN_COLUMNS = new Set(['label', 'axis', 'n']);

interface Memory {
  sorts: Sorts;
  /** The state the tab opened with, in its normal form; none before it is read. */
  opened: ViewState | null;
}

const sortable = (state: ViewState, sort: Sort) => OWN_COLUMNS.has(sort.column) || state.measures.some((measure) => measureKey(measure) === sort.column);

const same = (one: Sort | null, other: Sort | null) => one?.column === other?.column && one?.direction === other?.direction;

/** The sort the tab remembers for what `state` asks, where the view shows its column. */
function remembered({ sorts, opened }: Memory, state: ViewState, dimensions: Catalogue | undefined): Sort | null {
  const key = asked(state, dimensions);
  const kept = key in sorts ? sorts[key] : opened !== null && asked(opened, dimensions) === key ? opened.sort : null;
  return kept !== null && sortable(state, kept) ? kept : null;
}

/** The one measure `next` changed in place of `was`'s, by their keys; none where the measures were added, removed or moved. */
function changedInPlace(was: readonly string[], next: readonly string[]): { from: string; to: string } | null {
  if (was.length !== next.length) return null;
  const at = next.flatMap((key, index) => (key === was[index] ? [] : [index]));
  return at.length === 1 && !was.includes(next[at[0]]) ? { from: was[at[0]], to: next[at[0]] } : null;
}

/**
 * The view moved from `was` to `next`, and the sorts the tab remembers then: a measure changed in
 * place takes its sorts along, the view's and those remembered, and one hidden forgets them; a move
 * that lands on what is asked anew with the sort let go takes the one remembered for it; a sort
 * picked or carried for what the view still asks is remembered.
 */
export function settle(memory: Memory, was: ViewState, next: ViewState, dimensions: Catalogue | undefined): { state: ViewState; sorts: Sorts } {
  const sorts: Record<string, Sort | null> = { ...memory.sorts };
  let sort = next.sort;
  const before = was.measures.map(measureKey);
  const after = next.measures.map(measureKey);
  if (before.join('&') !== after.join('&')) {
    const renamed = changedInPlace(before, after);
    const carried = (kept: Sort): Sort | null => {
      const moved = renamed !== null && kept.column === renamed.from ? { ...kept, column: renamed.to } : kept;
      return sortable(next, moved) ? moved : null;
    };
    const { opened } = memory;
    if (opened?.sort != null) {
      const key = asked(opened, dimensions);
      if (!(key in sorts)) sorts[key] = opened.sort;
    }
    for (const [key, kept] of Object.entries(sorts)) if (kept !== null) sorts[key] = carried(kept);
    if (sort !== null) sort = carried(sort);
  }
  const here = asked(next, dimensions);
  if (sort === null && here !== asked(was, dimensions)) sort = remembered({ sorts, opened: memory.opened }, next, dimensions);
  else if (sort !== null && here === asked(was, dimensions) && !same(sort, was.sort)) sorts[here] = sort;
  return { state: { ...next, sort }, sorts };
}

/** A heading's press on `column`, the answer sorted by `drawn`: descending first, then the other way. */
export function sortedBy(drawn: Sort, column: string): Sort {
  return { column, direction: drawn.column === column && drawn.direction === 'desc' ? 'asc' : 'desc' };
}

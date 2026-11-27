/**
 * The headings of a view's measures, what they read and what they do (F163.4; the mockup's
 * `heads.js`): a press on a heading's name sorts by its column, largest first and then the other
 * way; its × removes its measure, the last one having none; its menu's sign opens its panel, which
 * a change in it leaves open, since the panel is held by the measure's place and not by the
 * answer; a change in place sets the measure there.
 *
 * A heading is dragged to move its column: a press and a move of more than 4 px lift it, its name
 * following the pointer, and a line marks where it would drop, between two columns, where that
 * moves it; a release there moves it, Esc or a release on its own place leaves it, and the
 * release's click sorts nothing. What a drag holds is the page's, read on each move from the
 * columns' extents the presentation marks with `data-slot`, the measure's place: the walk's event
 * reading the rows again under it leaves it as it is. Where the rows keep the first measure's sort
 * by default, a move pins it to that measure, which would otherwise hand it to the new first one.
 * Each of these moves replaces the entry (F160.4), the mockup's.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { useViewWords } from '@/hooks/use-view-words';
import type { Words } from '@/lib/dashboard/describe';
import { changed, measureNames, moved, removed } from '@/lib/dashboard/measures';
import { stateOf } from '@/lib/dashboard/queries';
import type { Rows } from '@/lib/dashboard/rows-layout';
import { sortedBy } from '@/lib/dashboard/sorts';
import { measureKey, readState, type ViewState } from '@/lib/dashboard/state';

type Measure = ViewState['measures'][number];

/** The view moved to `state`, a new entry, or the entry in place where `replace`. */
type Place = (state: ViewState, replace?: boolean) => void;

/** The pointer's travel that lifts a heading, in pixels. */
const LIFT = 4;

/** A heading lifted and dragged. */
interface Drag {
  /** Its measure's place among the columns, and its name. */
  from: number;
  name: string;
  /** Where its name is drawn, following the pointer. */
  left: number;
  top: number;
  /** The line marking the drop, where it moves the column. */
  mark: { left: number; top: number; height: number } | null;
}

/** The headings of the view drawn: what they read and what they do. */
export interface Heads {
  state: ViewState;
  /** The answer drawn. */
  rows: Rows;
  /** Each of its measures' name, and its heading's tooltip. */
  names: readonly string[];
  titles: readonly string[];
  /** The heading whose panel is open, by its measure's place. */
  open: number | null;
  toggle: (j: number) => void;
  close: () => void;
  drag: Drag | null;
  sort: (j: number) => void;
  remove: (j: number) => void;
  press: (j: number, event: ReactPointerEvent<HTMLElement>) => void;
  change: (j: number, measure: Measure) => void;
}

/** The answer drawn is of the state's measures, in their order. */
const inStep = (state: ViewState, rows: Rows) => state.measures.map(measureKey).join('&') === rows.measures.map((measure) => measure.key).join('&');

/** A measure's figure's line, or its ratio's. */
function lineOf(measure: Measure | undefined, words: Words): string | null {
  if (measure?.kind === 'simple') return words.measures?.figures?.find((figure) => figure.key === measure.figure)?.line ?? null;
  if (measure?.kind === 'ratio') return words.measures?.ratios?.find((ratio) => ratio.key === measure.key)?.line ?? null;
  return null;
}

/** Each column's extent sideways, in the measures' order: the union of its `data-slot` elements. */
function slotsOf(chart: Element): { left: number; right: number; top: number }[] {
  const by = new Map<number, { left: number; right: number; top: number }>();
  for (const slot of chart.querySelectorAll<HTMLElement>('[data-slot]')) {
    const box = slot.getBoundingClientRect();
    const j = Number(slot.dataset.slot);
    const was = by.get(j);
    by.set(j, was === undefined ? { left: box.left, right: box.right, top: box.top } : { left: Math.min(was.left, box.left), right: Math.max(was.right, box.right), top: Math.min(was.top, box.top) });
  }
  return [...by.keys()].sort((a, b) => a - b).map((j) => by.get(j)!);
}

/** The headings of `rows`, the view's answer drawn for `state`; none before both stand. */
export function useMeasureHeads(state: ViewState | null, rows: Rows | undefined, place: Place): Heads | null {
  const words = useViewWords();
  const [open, setOpen] = useState<number | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const names = rows === undefined ? [] : measureNames(rows, words);
  const latest = useRef({ state, rows, place, names });
  useLayoutEffect(() => {
    latest.current = { state, rows, place, names };
  });
  // A drag's listeners, taken off as it ends or as the view leaves.
  const ending = useRef<(() => void) | null>(null);
  useEffect(() => () => ending.current?.(), []);
  const close = useCallback(() => setOpen(null), []);

  const press = useCallback((j: number, event: ReactPointerEvent<HTMLElement>) => {
    const now = latest.current;
    if (event.button !== 0 || (event.target as Element).closest('.ctl, .dash-headpane') !== null) return;
    if (now.state === null || now.rows === undefined || now.state.measures.length < 2 || !inStep(now.state, now.rows)) return;
    const head = event.currentTarget;
    const chart = head.closest('.dash-chart')!;
    const start = { x: event.clientX, y: event.clientY };
    const grip = head.getBoundingClientRect();
    const name = now.names[j];
    let lifted = false;
    let off = false;
    let at: number | null = null;
    const onMove = (moving: PointerEvent) => {
      if (off) return;
      const slots = slotsOf(chart);
      if (!lifted) {
        if ((Math.abs(moving.clientX - start.x) < LIFT && Math.abs(moving.clientY - start.y) < LIFT) || slots.length < 2) return;
        lifted = true;
        setOpen(null);
        if (head.contains(document.activeElement)) (document.activeElement as HTMLElement).blur();
      }
      // The drop's place: the number of columns whose middle the pointer is past.
      const k = slots.filter((slot) => (slot.left + slot.right) / 2 < moving.clientX).length;
      at = k === j || k === j + 1 ? null : k;
      let mark: Drag['mark'] = null;
      if (at !== null) {
        const gap = (slots[1].left - slots[0].right) / 2;
        const edges = [slots[0].left - gap, ...slots.slice(1).map((slot, index) => (slots[index].right + slot.left) / 2), slots[slots.length - 1].right + gap];
        const main = head.closest('.dash-main')!.getBoundingClientRect();
        const bounds = (head.closest('.dash-tablewrap') ?? chart).getBoundingClientRect();
        const top = Math.max(Math.min(...slots.map((slot) => slot.top)), main.top, bounds.top);
        const bottom = Math.min(bounds.bottom, main.bottom);
        const x = edges[at];
        if (x >= Math.max(main.left, bounds.left) && x <= Math.min(main.right, bounds.right)) mark = { left: x - 1, top, height: Math.max(0, bottom - top) };
      }
      setDrag({ from: j, name, left: moving.clientX - (start.x - grip.left), top: moving.clientY - (start.y - grip.top), mark });
    };
    const end = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', end);
      window.removeEventListener('keydown', onKey, true);
      ending.current = null;
      setDrag(null);
    };
    const onUp = () => {
      end();
      if (!lifted) return;
      // The release's click is the drag's, not the heading's sort.
      const eat = (click: MouseEvent) => {
        click.stopPropagation();
        click.preventDefault();
      };
      window.addEventListener('click', eat, true);
      setTimeout(() => window.removeEventListener('click', eat, true), 0);
      const { state: was, rows: drawn, place: to } = latest.current;
      if (off || at === null || was === null || drawn === undefined || !inStep(was, drawn)) return;
      const next = moved(was, j, at);
      to(was.sort === null && drawn.measures.some((measure) => measure.key === drawn.sort.column) ? { ...next, sort: drawn.sort } : next, true);
    };
    // Esc puts the heading back; the release that follows is still the drag's, and moves nothing.
    const onKey = (key: KeyboardEvent) => {
      if (key.key !== 'Escape' || !lifted || off) return;
      key.stopPropagation();
      key.preventDefault();
      off = true;
      at = null;
      setDrag(null);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', end);
    window.addEventListener('keydown', onKey, true);
    ending.current = end;
  }, []);

  if (state === null || rows === undefined) return null;
  const shown = readState(stateOf(rows.address)).measures;
  const many = rows.measures.length > 1;
  const titles = rows.measures.map((answered, j) =>
    [names[j], lineOf(shown[j], words), answered.refused === null ? null : `Refused by ${rows.by.label}: ${answered.refused}`, many ? 'Drag to move the column' : null].filter(Boolean).join('\n'),
  );
  return {
    state,
    rows,
    names,
    titles,
    open,
    toggle: (j) => setOpen((was) => (was === j ? null : j)),
    close,
    drag,
    sort: (j) => {
      const column = rows.measures[j].key;
      if (state.measures.some((measure) => measureKey(measure) === column)) place({ ...state, sort: sortedBy(rows.sort, column) }, true);
    },
    remove: (j) => {
      const next = removed(state, rows.measures[j].key);
      if (next === state) return;
      setOpen(null);
      place(next, true);
    },
    press,
    change: (j, measure) => place(changed(state, j, measure), true),
  };
}

/**
 * The dashboard's view tabs (F161): each holds its view whole, its saved view, the state it opened
 * with, its state now and its scroll (F161.1), kept in the browser (`browser-state.ts`), read once
 * as the dashboard first opens in the page and written whole on every change, so that two windows
 * are never kept in step and a new build's reload finds the tabs as they were left (F160.10). The
 * order the tabs showed in is kept beside them, the latest first: the first is the tab at hand,
 * which `#dash` shows, and closing the tab showing goes back by it (F28.8).
 *
 * The address names the tab at hand and its state (`address.ts`), and the tabs follow it
 * (`useViewTabsAt`): a tab the address names takes the state it names; one it names that is not
 * open, or a state it names with no tab, opens a tab of its own, which the address is written back
 * in place to name. A move of the person's (`moves`) writes the address it leads to.
 */

import { useLayoutEffect, useSyncExternalStore } from 'react';
import { useRouter } from '@tanstack/react-router';
import { browserState, rememberViewTabs, type KeptViewTab, type KeptViewTabs } from '@/lib/browser-state';
import { placeOf } from '@/lib/dashboard/address';
import { DASH, hashOf } from '@/lib/screens';

export type ViewTab = KeptViewTab;

/** A saved view a tab opens, by its id and its name. */
interface OpenedView {
  id: string;
  name: string;
}

/** The barest view that draws: this quota week, by project, cost alone (`backend/dashboard-states/states.json`). */
export const SCRATCH = 't=qw&by=project&m=cost.sum&col=none';

const TAB_ID = /^[A-Za-z0-9]+$/;

let kept: KeptViewTabs = browserState().viewTabs;
const listeners = new Set<() => void>();

function write(next: KeptViewTabs): void {
  kept = next;
  rememberViewTabs(next);
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const tabOf = (id: string) => kept.tabs.find((tab) => tab.id === id) ?? null;

function newId(): string {
  let id: string;
  do id = Math.random().toString(36).slice(2, 6);
  while (id.length < 4 || tabOf(id) !== null);
  return id;
}

/** A tab opened last in the line and brought to the front: on the panel, or on `now`; `id` taken where it is free. */
function add(id: string | null, now: string | null): ViewTab {
  const tab: ViewTab = { id: id !== null && TAB_ID.test(id) && tabOf(id) === null ? id : newId(), view: null, opened: now, now, scroll: 0 };
  write({ tabs: [...kept.tabs, tab], seen: [tab.id, ...kept.seen] });
  return tab;
}

function change(id: string, patch: Partial<ViewTab>): void {
  write({ ...kept, tabs: kept.tabs.map((tab) => (tab.id === id ? { ...tab, ...patch } : tab)) });
}

function bring(id: string): void {
  if (kept.seen[0] !== id) write({ ...kept, seen: [id, ...kept.seen.filter((each) => each !== id)] });
}

/** The address of `tab`, `#dash/<id>`, its state after it where it has one. */
const addressOf = (tab: ViewTab) => `${DASH}/${tab.id}${tab.now === null ? '' : `/${tab.now}`}`;

/** The tabs, and the one at hand: the first in the order they showed, none before the first opening. */
export function useViewTabs(): { tabs: readonly ViewTab[]; at: ViewTab | null } {
  const now = useSyncExternalStore(subscribe, () => kept);
  return { tabs: now.tabs, at: now.tabs.find((tab) => tab.id === now.seen[0]) ?? null };
}

/** The address, `hash`, taken by the tabs while the dashboard shows; written back in place where it names no tab of its own. */
export function useViewTabsAt(shown: boolean, hash: string): void {
  const router = useRouter();
  useLayoutEffect(() => {
    if (!shown) return;
    const place = placeOf(hash);
    const named = place.tab === null ? null : tabOf(place.tab);
    if (named !== null) {
      if (named.now !== place.state) change(named.id, { now: place.state, opened: named.opened ?? place.state });
      bring(named.id);
      return;
    }
    if (place.tab === null && place.state === null) {
      if (kept.seen.length === 0) add(null, null);
      return;
    }
    const tab = add(place.tab, place.state);
    if (tab.id !== place.tab) {
      const { href, state } = router.history.location;
      router.history.replace(href.slice(0, href.length - hashOf(href).length) + addressOf(tab), state);
    }
  }, [shown, hash, router]);
}

/** Where the main area of the tab `id` was scrolled to. */
export const scrollOf = (id: string) => tabOf(id)?.scroll ?? 0;

/** Keeps where the main area of the tab `id` is scrolled to, telling no one: nothing drawn reads it. */
export function keepScroll(id: string, top: number): void {
  if (tabOf(id) === null) return;
  kept = { ...kept, tabs: kept.tabs.map((tab) => (tab.id === id ? { ...tab, scroll: top } : tab)) };
  rememberViewTabs(kept);
}

/** The tabs that opened the saved view `id` take its new name. */
export function viewRenamed(id: string, name: string): void {
  if (kept.tabs.some((tab) => tab.view?.id === id)) write({ ...kept, tabs: kept.tabs.map((tab) => (tab.view?.id === id ? { ...tab, view: { id, name } } : tab)) });
}

/** The person's moves among the tabs, each writing the address it leads to: a new entry, but for a close. */
export function useViewTabMoves() {
  const router = useRouter();
  const go = (tab: ViewTab, replace = false) => {
    const href = router.history.location.href;
    const to = href.slice(0, href.length - hashOf(href).length) + addressOf(tab);
    if (replace) router.history.replace(to, router.history.location.state);
    else router.history.push(to, {});
  };
  /** The tab that shows after `gone` closed, the one that showed before it; a new one on the panel where none is left. */
  const after = (gone: readonly string[]): ViewTab => {
    const left = kept.tabs.filter((tab) => !gone.includes(tab.id));
    const seen = kept.seen.filter((id) => !gone.includes(id));
    write({ tabs: left, seen });
    const back = seen[0];
    return back === undefined ? add(null, null) : tabOf(back)!;
  };
  return {
    /** Another tab brought to the front, as it was left. */
    show: (id: string) => {
      bring(id);
      go(tabOf(id)!);
    },
    /** A new tab, on the panel. */
    open: () => go(add(null, null)),
    /** A view opened in the tab `id` from its panel, a saved view or, with none, the start from scratch. */
    openView: (id: string, view: OpenedView | null, state: string) => {
      change(id, { view, opened: state, now: state, scroll: 0 });
      go(tabOf(id)!);
    },
    close: (id: string) => {
      if (kept.seen[0] !== id) {
        write({ tabs: kept.tabs.filter((tab) => tab.id !== id), seen: kept.seen.filter((each) => each !== id) });
        return;
      }
      go(after([id]), true);
    },
    closeAll: () => go(after(kept.tabs.map((tab) => tab.id)), true),
  };
}

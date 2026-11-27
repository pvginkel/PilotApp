/**
 * The dashboard's view tabs (F161): each holds its view whole, its saved view, the state it opened
 * with, its state now, the sorts it remembers by By (`sorts.ts`) and its scroll (F161.1), kept in the browser (`browser-state.ts`), read once
 * as the dashboard first opens in the page and written whole on every change, so that two windows
 * are never kept in step and a new build's reload finds the tabs as they were left (F160.10). The
 * order the tabs showed in is kept beside them, the latest first: the first is the tab at hand,
 * which `#dash` shows, and closing the tab showing goes back by it (F28.8).
 *
 * The address names the tab at hand and its state (`address.ts`), and the tabs follow it
 * (`useViewTabsAt`). An entry the dashboard writes is its own: it carries its tab's id, the saved
 * view the tab is of and the state it opened with in the history's state (`DashEntry`). Back and
 * Forward to an entry of its own move its tab's state alone, the tab keeping its name and what Reset
 * goes back to; a closed tab's entry opens it again as it was (F160.4). Any other entry is a link,
 * opened cold, typed, or a reply's: it shows the tab already showing its state, in the server's
 * normal form, else a tab of its own, never another state in a tab that is open, and the address is
 * written back in place to name the tab (F161.3). A move of the person's (`moves`) writes the address
 * it leads to: a new entry, but for a close and what replaces the entry (F160.4).
 */

import { useLayoutEffect, useSyncExternalStore } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useRouter, useRouterState } from '@tanstack/react-router';
import { browserState, rememberViewTabs, type KeptViewTab, type KeptViewTabs } from '@/lib/browser-state';
import { placeOf } from '@/lib/dashboard/address';
import { addressQuery, stateOf } from '@/lib/dashboard/queries';
import { DASH, hashOf, screenOf } from '@/lib/screens';

export type ViewTab = KeptViewTab;

/** A saved view a tab opens, by its id and its name. */
interface OpenedView {
  id: string;
  name: string;
}

/** What an entry of the dashboard's own carries of its tab: its id, the saved view it is of, the state it opened with. */
interface DashEntry {
  tab: string;
  view: OpenedView | null;
  opened: string | null;
}

declare module '@tanstack/react-router' {
  interface HistoryState {
    /** The entry is the dashboard's own, of this tab (F160.4). */
    dash?: DashEntry;
  }
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
function add(id: string | null, now: string | null, view: OpenedView | null = null, opened: string | null = now): ViewTab {
  const tab: ViewTab = { id: id !== null && TAB_ID.test(id) && tabOf(id) === null ? id : newId(), view, opened, now, sorts: {}, scroll: 0 };
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

/** The history's state of an entry of `tab`'s own, with none of the app's. */
const entryOf = (tab: ViewTab) => ({ dash: { tab: tab.id, view: tab.view, opened: tab.opened } });

/** An href without its hash. */
const pathOf = (href: string) => href.slice(0, href.length - hashOf(href).length);

/** The normal form of `written`, a state as an address carries it; none where the server refuses it. */
const normalOf = (queryClient: QueryClient, written: string) =>
  queryClient.fetchQuery(addressQuery(queryClient, written)).then(
    (answer) => stateOf(answer.address),
    () => null,
  );

/** The tabs, and the one at hand: the first in the order they showed, none before the first opening. */
export function useViewTabs(): { tabs: readonly ViewTab[]; at: ViewTab | null } {
  const now = useSyncExternalStore(subscribe, () => kept);
  return { tabs: now.tabs, at: now.tabs.find((tab) => tab.id === now.seen[0]) ?? null };
}

/**
 * The address taken by the tabs while the dashboard shows. It is read off the history as the effect
 * runs, not as the render saw it: StrictMode runs a mounting effect twice over one render, and the
 * second run finds the address the first wrote back. A link's normal forms, where the page has not
 * read them, are asked first; a newer address drops the answer.
 */
export function useViewTabsAt(shown: boolean): void {
  const router = useRouter();
  const queryClient = useQueryClient();
  const href = useRouterState({ select: (state) => state.location.href });
  useLayoutEffect(() => {
    if (!shown) return undefined;
    const { href: at, state } = router.history.location;
    const place = placeOf(hashOf(at));
    if (place.tab === null && place.state === null) {
      if (kept.seen.length === 0) add(null, null);
      return undefined;
    }
    const named = place.tab === null ? null : tabOf(place.tab);
    const own = place.tab !== null && state.dash?.tab === place.tab ? state.dash : undefined;
    if (own !== undefined) {
      if (named === null) add(place.tab, place.state, own.view, own.opened ?? place.state);
      else {
        if (named.now !== place.state) change(named.id, { now: place.state, opened: named.opened ?? place.state });
        bring(named.id);
      }
      return undefined;
    }
    /** The link's entry, in place, the tab's own. */
    const take = (tab: ViewTab) => {
      bring(tab.id);
      router.history.replace(pathOf(at) + addressOf(tab), entryOf(tab));
    };
    const wanted = place.state;
    if (wanted === null) {
      take(named ?? add(place.tab, null));
      return undefined;
    }
    // The tab named first, of those that show the link's state.
    const first = (tabs: readonly ViewTab[]) => tabs.find((tab) => tab.id === place.tab) ?? tabs[0];
    const showing = kept.tabs.filter((tab) => tab.now !== null);
    const same = first(showing.filter((tab) => tab.now === wanted));
    if (same !== undefined || showing.length === 0) {
      take(same ?? add(place.tab, wanted));
      return undefined;
    }
    let live = true;
    void Promise.all([wanted, ...showing.map((tab) => tab.now!)].map((written) => normalOf(queryClient, written))).then(([normal, ...forms]) => {
      if (!live) return;
      // A tab closed or moved meanwhile is no longer showing what was asked of it.
      const hits = showing.filter((tab, index) => normal !== null && forms[index] === normal && tabOf(tab.id)?.now === tab.now);
      take(first(hits) ?? add(place.tab, wanted));
    });
    return () => {
      live = false;
    };
  }, [shown, href, router, queryClient]);
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
    const to = pathOf(router.history.location.href) + addressOf(tab);
    if (replace) router.history.replace(to, entryOf(tab));
    else router.history.push(to, entryOf(tab));
  };
  /** The tab that shows after `gone` closed, the one that showed before it; a new one on the panel where none is left. */
  const after = (gone: readonly string[]): ViewTab => {
    const left = kept.tabs.filter((tab) => !gone.includes(tab.id));
    const seen = kept.seen.filter((id) => !gone.includes(id));
    write({ tabs: left, seen });
    const back = seen[0];
    return back === undefined ? add(null, null) : tabOf(back)!;
  };
  /**
   * The tab at hand, `id`, on the state `now`: a new entry, or the entry in place where `replace`, a
   * selection's, a look's, a sort's and a measure's (F160.4); with `sorts`, those it remembers then.
   */
  const set = (id: string, now: string, replace = false, sorts?: ViewTab['sorts']) => {
    change(id, sorts === undefined ? { now } : { now, sorts });
    go(tabOf(id)!, replace);
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
      change(id, { view, opened: state, now: state, sorts: {}, scroll: 0 });
      go(tabOf(id)!);
    },
    set,
    /** The tab `id` back to what it opened with (F161.5), the sorts it remembered forgotten but the one that holds. */
    reset: (id: string) => set(id, tabOf(id)!.opened!, false, {}),
    /**
     * The tab `id` saved as `view`, which holds `opened`: its name and what Reset goes back to. Its
     * entry takes them in place, where the address still names it.
     */
    saved: (id: string, view: OpenedView, opened: string) => {
      if (tabOf(id) === null) return;
      change(id, { view, opened });
      const { href } = router.history.location;
      const hash = hashOf(href);
      if (screenOf(hash) === 'dashboard' && placeOf(hash).tab === id) router.history.replace(href, entryOf(tabOf(id)!));
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

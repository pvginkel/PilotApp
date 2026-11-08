/**
 * The desktop's tab line (F28.8): each project's own, its documents in the order they opened and
 * the order the tabs showed in, the timeline's among them, which closing the tab showing goes back
 * by. The tab showing is the address's (F97): a document's, an attachment's, the handbook's or the
 * project document's shows its tab, opening it at the line's end where it is not open, in the
 * frame the address is first drawn in; any other address of the project shows the timeline. A
 * tab's change replaces the browser's entry, so that Back does not move between tabs. The line and
 * the order the tabs showed in are kept in the browser (F133), so that after a reload the line is
 * as it was left, and the project's row in the list brings back the tab it was left on (F1.6).
 * Each tab's scroll is kept while another shows, as long as the page (F28.1). Nothing of it is on
 * a phone, whose documents are views (F98.4).
 */

import { createContext, useContext, useLayoutEffect, useSyncExternalStore } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useShownProject } from '@/hooks/use-project-address';
import { browserState, rememberLine, type DocTab, type KeptLine } from '@/lib/browser-state';

declare module '@tanstack/react-router' {
  interface HistoryState {
    /**
     * Gone to from the project's row in the list, which off a phone shows the tab it was left on
     * (F1.6): the project's id, which its line is kept by.
     */
    fromList?: string;
  }
}

/** The timeline's key in the order the tabs showed in: a draft's definition chat in its place. */
export const TIMELINE = 'timeline';

interface Line extends KeptLine {
  /** The key of the address the line last took its tab from, none before the page showed one. */
  synced: string | null;
}

const EMPTY: Line = { tabs: [], seen: [], synced: null };
/** Each project's line in this page, from the one the browser keeps. */
const lines = new Map<string, Line>();
const listeners = new Set<() => void>();
/** Each project's tabs' scroll, by the tab's key. */
const scrolls = new Map<string, Map<string, number>>();

function lineOf(projectId: string): Line {
  let line = lines.get(projectId);
  if (line === undefined) {
    line = { ...EMPTY, ...browserState().lines[projectId] };
    lines.set(projectId, line);
  }
  return line;
}

function write(projectId: string, line: Line): void {
  lines.set(projectId, line);
  rememberLine(projectId, line);
  listeners.forEach((listener) => listener());
}

/** The tab the project's line was left on, none for the timeline. */
export function tabLeftOn(projectId: string): DocTab | null {
  const { tabs, seen } = lineOf(projectId);
  return tabs.find((tab) => tab.key === seen[0]) ?? null;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function scrollsOf(projectId: string): Map<string, number> {
  let kept = scrolls.get(projectId);
  if (kept === undefined) {
    kept = new Map();
    scrolls.set(projectId, kept);
  }
  return kept;
}

/** What the tab showing is given (`Overlay`): its close, and its scroll as it was left. */
export interface ShownTab {
  close: () => void;
  scroll: number;
  /** Keeps its scroll as it scrolls. */
  keep: (top: number) => void;
}

/** The desktop's tab showing a document, to what it shows; none in the overlay and on a phone. */
export const DocTabContext = createContext<ShownTab | null>(null);

/**
 * Whether a move to another of the project's addresses replaces the browser's entry: on the
 * desktop, where the address follows the tab showing (F97).
 */
export const TabMovesContext = createContext(false);

/** `replace` for a link or a navigation to another of the project's addresses. */
export function useTabReplace(): boolean {
  return useContext(TabMovesContext);
}

export interface TabLine {
  /** The open tabs, in the order they opened. */
  tabs: readonly DocTab[];
  /** The key of the tab showing, `TIMELINE` for the timeline. */
  on: string;
  /** Shows the tab, none for the timeline. */
  show: (tab: DocTab | null) => void;
  /** Closes the tab, showing the one that showed before it where it is the tab showing. */
  close: (key: string) => void;
  closeAll: () => void;
  /** What the tab showing, by its key, is given. */
  shown: (key: string) => ShownTab;
}

/** The shown project's tab line, `showing` the tab the address shows, none for the timeline. */
export function useDocTabs(showing: DocTab | null): TabLine {
  const { id: projectId, address } = useShownProject();
  const line = useSyncExternalStore(subscribe, () => lineOf(projectId));
  const navigate = useNavigate();
  const key = showing?.key ?? TIMELINE;
  const fresh = key !== line.synced;
  const tabs = fresh && showing !== null && !line.tabs.some((tab) => tab.key === key) ? [...line.tabs, showing] : line.tabs;
  const on = fresh ? key : (line.seen[0] ?? TIMELINE);
  const kind = showing?.kind;
  const id = showing?.id ?? null;
  const documentId = showing?.documentId;
  const href = showing?.href;

  useLayoutEffect(() => {
    const now = lineOf(projectId);
    const tab = kind === undefined ? null : { key, kind, id, documentId, href: href! };
    const open = tab === null || now.tabs.some((each) => each.key === key);
    write(projectId, {
      // An attachment reached at another of its addresses shows its tab at that one.
      tabs: open ? now.tabs.map((each) => (each.key === key ? tab! : each)) : [...now.tabs, tab],
      seen: [key, ...now.seen.filter((each) => each !== key)],
      synced: key,
    });
  }, [projectId, key, kind, id, documentId, href]);

  const show = (tab: DocTab | null) =>
    void (tab === null
      ? navigate({ to: '/projects/$address', params: { address }, replace: true })
      : navigate({ href: tab.href, replace: true }));
  const close = (closed: string) => {
    const now = lineOf(projectId);
    const left = now.tabs.filter((tab) => tab.key !== closed);
    const seen = now.seen.filter((each) => each !== closed);
    scrollsOf(projectId).delete(closed);
    write(projectId, { ...now, tabs: left, seen });
    if (closed !== on) return;
    const back = seen[0] ?? TIMELINE;
    show(left.find((tab) => tab.key === back) ?? null);
  };
  return {
    tabs,
    on,
    show,
    close,
    closeAll: () => {
      scrolls.delete(projectId);
      write(projectId, { ...EMPTY, synced: lineOf(projectId).synced });
      if (on !== TIMELINE) show(null);
    },
    shown: (shownKey) => ({
      close: () => close(shownKey),
      scroll: scrollsOf(projectId).get(shownKey) ?? 0,
      keep: (top) => void scrollsOf(projectId).set(shownKey, top),
    }),
  };
}

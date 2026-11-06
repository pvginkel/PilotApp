/**
 * The desktop's tab line (F28.8): each project's own, its documents in the order they opened and
 * the order the tabs showed in, the timeline's among them, which closing the tab showing goes back
 * by. The tab showing is the address's (F97): a document's, an attachment's, the handbook's or the
 * project document's shows its tab, opening it at the line's end where it is not open, in the
 * frame the address is first drawn in; any other address of the project shows the timeline. A
 * tab's change replaces the browser's entry, so that Back does not move between tabs. Each tab's
 * scroll is kept while another shows (F28.1). The line lives as long as the page; nothing of it is
 * on a phone, whose documents are views (F98.4).
 */

import { createContext, useContext, useLayoutEffect, useSyncExternalStore } from 'react';
import { useNavigate } from '@tanstack/react-router';

export type DocTabKind = 'document' | 'attachment' | 'handbook' | 'project-document';

/** A tab of the line: what it shows, and the address that shows it again. */
export interface DocTab {
  /** One per thing shown: `document <item>`, `attachment <attachment>`, `handbook`, `project-document`. */
  key: string;
  kind: DocTabKind;
  /** The item's or the attachment's id; none for the handbook and the project document. */
  id: string | null;
  href: string;
}

/** The timeline's key in the order the tabs showed in: a draft's definition chat in its place. */
export const TIMELINE = 'timeline';

interface Line {
  tabs: readonly DocTab[];
  /** The keys in the order they last showed, the latest first. */
  seen: readonly string[];
  /** The key of the address the line last took its tab from. */
  synced: string | null;
}

const EMPTY: Line = { tabs: [], seen: [], synced: null };
const lines = new Map<string, Line>();
const listeners = new Set<() => void>();
/** Each project's tabs' scroll, by the tab's key. */
const scrolls = new Map<string, Map<string, number>>();

const lineOf = (projectId: string): Line => lines.get(projectId) ?? EMPTY;

function write(projectId: string, line: Line): void {
  lines.set(projectId, line);
  listeners.forEach((listener) => listener());
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

/** The project's tab line, `showing` the tab the address shows, none for the timeline. */
export function useDocTabs(projectId: string, showing: DocTab | null): TabLine {
  const line = useSyncExternalStore(subscribe, () => lineOf(projectId));
  const navigate = useNavigate();
  const key = showing?.key ?? TIMELINE;
  const fresh = key !== line.synced;
  const tabs = fresh && showing !== null && !line.tabs.some((tab) => tab.key === key) ? [...line.tabs, showing] : line.tabs;
  const on = fresh ? key : (line.seen[0] ?? TIMELINE);
  const kind = showing?.kind;
  const id = showing?.id ?? null;
  const href = showing?.href;

  useLayoutEffect(() => {
    const now = lineOf(projectId);
    const tab = kind === undefined ? null : { key, kind, id, href: href! };
    const open = tab === null || now.tabs.some((each) => each.key === key);
    write(projectId, {
      // An attachment reached at another of its addresses shows its tab at that one.
      tabs: open ? now.tabs.map((each) => (each.key === key ? tab! : each)) : [...now.tabs, tab],
      seen: [key, ...now.seen.filter((each) => each !== key)],
      synced: key,
    });
  }, [projectId, key, kind, id, href]);

  const show = (tab: DocTab | null) =>
    void (tab === null
      ? navigate({ to: '/projects/$projectId', params: { projectId }, replace: true })
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

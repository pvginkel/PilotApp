/**
 * What the browser remembers (F133): kept in its storage, nothing of it on the server. Unsent text
 * is kept under a key of its own, read when its field opens and written as it is typed, and beside
 * it the quote a composer's field carries and a one-ask item's choice before its Send (F32.3).
 */

import { useSyncExternalStore } from 'react';
import type { QuoteRef } from '@/lib/chat/quotes';
import { pathWithin } from '@/lib/project-paths';

export const THEMES = ['system', 'light', 'dark'] as const;
export type Theme = (typeof THEMES)[number];

/** The project list's collapsible groups (F1.5, F1.7). */
export const GROUPS = ['others', 'finished'] as const;
export type Group = (typeof GROUPS)[number];

/**
 * The side panel's tabs: an open project's Chat and Documents (F38.1), with Conversations between
 * them once a session has talked to Pilot about it (F150.12), a draft's Draft and Documents
 * (F46.3). The first is the one a panel opens on until the person picks another.
 */
export const PANEL_TABS = ['chat', 'draft', 'conversations', 'documents'] as const;
export type PanelTab = (typeof PANEL_TABS)[number];

/** A project's side panel as the person last left it: its tab. */
interface Panel {
  tab: PanelTab;
}

/**
 * The side panel's width off a phone, as the person last dragged it (R12): one for every project,
 * in pixels, and one for every draft, a share of the window, so that it stays half on another
 * screen. Until dragged, 420 px and half.
 */
interface PanelWidths {
  project: number;
  draft: number;
}

const PANEL_WIDTHS: PanelWidths = { project: 420, draft: 0.5 };

/** What a tab of the desktop's tab line shows (F28.8). */
const DOC_TAB_KINDS = ['document', 'attachment', 'handbook', 'journal', 'project-document'] as const;
type DocTabKind = (typeof DOC_TAB_KINDS)[number];

/** A tab of the line: what it shows, and the path within its project that shows it again. */
export interface DocTab {
  /** One per thing shown: `document <item>`, `attachment <attachment>`, `handbook`, `journal`, `project-document`. */
  key: string;
  kind: DocTabKind;
  /** The item's or the attachment's id; none for the handbook, the journal and the project document. */
  id: string | null;
  /** An attachment's at its document's address: the document, whose read its body waits on. */
  documentId?: string;
  /** `documents/<id>`: its address is built from the one its project is at (`project-paths.ts`). */
  path: string;
}

/** A project's tab line as the person last left it (F28.8). */
export interface KeptLine {
  /** The open tabs, in the order they opened. */
  tabs: readonly DocTab[];
  /** The keys in the order they last showed, the latest first, the timeline's among them. */
  seen: readonly string[];
}

/** A view tab of the dashboard as the person left it (F161.1): what it holds of its view. */
export interface KeptViewTab {
  /** Its id in the dashboard's address, letters and digits. */
  id: string;
  /** The saved view it opened from: its id, and its name as last read; none from scratch or a link. */
  view: { id: string; name: string } | null;
  /** The state it opened with, as an address carries it; none before it had one. */
  opened: string | null;
  /** Its state now, as an address carries it; none while it shows the new tab's panel. */
  now: string | null;
  /** The sort it remembers for what each of its states asks, a By or a series' axis; none where the one it opened with is forgotten (`sorts.ts`). */
  sorts: Readonly<Record<string, KeptSort | null>>;
  /** Where its main area was scrolled to. */
  scroll: number;
}

/** A sort a view tab remembers: a direction and the column it is by. */
interface KeptSort {
  direction: 'asc' | 'desc';
  column: string;
}

/** The dashboard's view tabs as the person left them (F161.1, F160.10). */
export interface KeptViewTabs {
  /** The open tabs, in the order they opened. */
  tabs: readonly KeptViewTab[];
  /** Their ids in the order they last showed, the latest first. */
  seen: readonly string[];
}

interface BrowserState {
  theme: Theme;
  /** The project last on screen, which the bare address opens (F1.6). */
  project: string | null;
  /** Each group's chevron as the person last set it: open or not. */
  chevrons: Record<Group, boolean>;
  /** Each project's side panel, by the project's id, once the person set it (F1.6, F38.1). */
  panels: Record<string, Panel>;
  panelWidths: PanelWidths;
  /** Each project's tab line, by the project's id, while a tab of it is open (F1.6, F28.8). */
  lines: Record<string, KeptLine>;
  /** The dashboard's view tabs, written whole by the window that changed them, never merged with another's. */
  viewTabs: KeptViewTabs;
  /**
   * The gold bar's offer of this browser's notifications answered (F146.2): its Turn on or its Not
   * now tapped, or the profile page's switch having turned them on.
   */
  notificationsOffered: boolean;
  /** The handle of the person this browser's push subscription was written for, while it stands (F146). */
  subscribedFor: string | null;
}

const STORAGE_KEY = 'pilot';

function load(): BrowserState {
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<Record<keyof BrowserState, unknown>>;
  const chevrons = (typeof saved.chevrons === 'object' && saved.chevrons !== null ? saved.chevrons : {}) as Partial<
    Record<Group, unknown>
  >;
  return {
    theme: THEMES.find((theme) => theme === saved.theme) ?? 'system',
    project: typeof saved.project === 'string' ? saved.project : null,
    chevrons: { others: chevrons.others === true, finished: chevrons.finished === true },
    panels: loadPanels(saved.panels),
    panelWidths: loadPanelWidths(saved.panelWidths),
    lines: loadLines(saved.lines),
    viewTabs: loadViewTabs(saved.viewTabs),
    notificationsOffered: saved.notificationsOffered === true,
    subscribedFor: typeof saved.subscribedFor === 'string' ? saved.subscribedFor : null,
  };
}

function loadPanels(saved: unknown): Record<string, Panel> {
  if (typeof saved !== 'object' || saved === null) return {};
  const panels: Record<string, Panel> = {};
  for (const [projectId, panel] of Object.entries(saved as Record<string, unknown>)) {
    if (typeof panel !== 'object' || panel === null) continue;
    const { tab } = panel as Partial<Record<keyof Panel, unknown>>;
    panels[projectId] = { tab: PANEL_TABS.find((each) => each === tab) ?? PANEL_TABS[0] };
  }
  return panels;
}

function loadPanelWidths(saved: unknown): PanelWidths {
  const { project, draft } = (typeof saved === 'object' && saved !== null ? saved : {}) as Partial<Record<keyof PanelWidths, unknown>>;
  return {
    project: typeof project === 'number' && project > 0 ? project : PANEL_WIDTHS.project,
    draft: typeof draft === 'number' && draft > 0 && draft < 1 ? draft : PANEL_WIDTHS.draft,
  };
}

function loadLines(saved: unknown): Record<string, KeptLine> {
  if (typeof saved !== 'object' || saved === null) return {};
  const lines: Record<string, KeptLine> = {};
  for (const [projectId, line] of Object.entries(saved as Record<string, unknown>)) {
    if (typeof line !== 'object' || line === null) continue;
    const { tabs, seen } = line as Partial<Record<keyof KeptLine, unknown>>;
    const kept = Array.isArray(tabs) ? tabs.flatMap(docTabOf) : [];
    if (kept.length === 0) continue;
    const shown = Array.isArray(seen) ? seen.filter((key): key is string => typeof key === 'string') : [];
    lines[projectId] = { tabs: kept, seen: shown };
  }
  return lines;
}

/** The tab as kept, none where it is no tab: one kept by its address, `href`, is at the address's path. */
function docTabOf(tab: unknown): DocTab[] {
  if (typeof tab !== 'object' || tab === null) return [];
  const { key, kind, id, documentId, path, href } = tab as Partial<Record<keyof DocTab | 'href', unknown>>;
  const at = typeof path === 'string' ? path : typeof href === 'string' ? pathWithin(href) : undefined;
  const of = DOC_TAB_KINDS.find((each) => each === kind);
  if (typeof key !== 'string' || of === undefined || at === undefined) return [];
  if (id !== null && typeof id !== 'string') return [];
  if (documentId !== undefined && typeof documentId !== 'string') return [];
  return [{ key, kind: of, id, documentId, path: at }];
}

const TAB_ID = /^[A-Za-z0-9]+$/;

function loadViewTabs(saved: unknown): KeptViewTabs {
  const { tabs, seen } = (typeof saved === 'object' && saved !== null ? saved : {}) as Partial<Record<keyof KeptViewTabs, unknown>>;
  const kept = Array.isArray(tabs) ? tabs.flatMap(viewTabOf) : [];
  const ids = new Set(kept.map((tab) => tab.id));
  const shown = Array.isArray(seen) ? seen.filter((id): id is string => typeof id === 'string' && ids.has(id)) : [];
  return { tabs: kept, seen: shown };
}

/** The tab as kept, none where it is no tab. */
function viewTabOf(tab: unknown): KeptViewTab[] {
  if (typeof tab !== 'object' || tab === null) return [];
  const { id, view, opened, now, sorts, scroll } = tab as Partial<Record<keyof KeptViewTab, unknown>>;
  if (typeof id !== 'string' || !TAB_ID.test(id)) return [];
  const text = (value: unknown) => (typeof value === 'string' ? value : null);
  const { id: viewId, name } = (typeof view === 'object' && view !== null ? view : {}) as Record<string, unknown>;
  return [
    {
      id,
      view: typeof viewId === 'string' && typeof name === 'string' ? { id: viewId, name } : null,
      opened: text(opened),
      now: text(now),
      sorts: loadSorts(sorts),
      scroll: typeof scroll === 'number' && scroll > 0 ? scroll : 0,
    },
  ];
}

/** A view tab's sorts as kept, those that are no sort left out. */
function loadSorts(saved: unknown): Record<string, KeptSort | null> {
  if (typeof saved !== 'object' || saved === null) return {};
  const sorts: Record<string, KeptSort | null> = {};
  for (const [asked, sort] of Object.entries(saved as Record<string, unknown>)) {
    if (sort === null) sorts[asked] = null;
    else if (typeof sort === 'object') {
      const { direction, column } = sort as Partial<Record<keyof KeptSort, unknown>>;
      if ((direction === 'asc' || direction === 'desc') && typeof column === 'string') sorts[asked] = { direction, column };
    }
  }
  return sorts;
}

let state = load();
const listeners = new Set<() => void>();

export function browserState(): BrowserState {
  return state;
}

/** Writes only what changed over what is stored, so that what another tab chose stays. */
export function rememberInBrowser(change: Partial<BrowserState>): void {
  state = { ...state, ...change };
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...load(), ...change }));
  listeners.forEach((listener) => listener());
}

/** Keeps a project's side panel as the person set it, over what another tab keeps for the others. */
export function rememberPanel(projectId: string, panel: Panel): void {
  rememberInBrowser({ panels: { ...load().panels, [projectId]: panel } });
}

/** Keeps the width of every project's side panel, or of every draft's, over what another tab keeps for the other. */
export function rememberPanelWidth(kind: keyof PanelWidths, width: number): void {
  rememberInBrowser({ panelWidths: { ...load().panelWidths, [kind]: width } });
}

/** Keeps a project's tab line as the person left it, over what another tab keeps for the others; nothing once no tab is open. */
export function rememberLine(projectId: string, line: KeptLine): void {
  const lines = { ...load().lines };
  if (line.tabs.length === 0) delete lines[projectId];
  else lines[projectId] = { tabs: line.tabs, seen: line.seen };
  rememberInBrowser({ lines });
}

/** Keeps the dashboard's view tabs as this window has them, over what another window kept of them. */
export function rememberViewTabs(viewTabs: KeptViewTabs): void {
  rememberInBrowser({ viewTabs });
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useBrowserState(): BrowserState {
  return useSyncExternalStore(subscribe, browserState);
}

const UNSENT_KEY = 'pilot.unsent';

function readUnsent(): Record<string, unknown> {
  return JSON.parse(localStorage.getItem(UNSENT_KEY) ?? '{}') as Record<string, unknown>;
}

/** What was typed into the field `field` and not sent. */
export function unsentText(field: string): string | undefined {
  const text = readUnsent()[field];
  return typeof text === 'string' ? text : undefined;
}

/** Keeps what is typed into a field until it is sent, over what another tab keeps; none, nothing kept. */
export function keepUnsent(field: string, text: string): void {
  const unsent = readUnsent();
  if (text === '') delete unsent[field];
  else unsent[field] = text;
  localStorage.setItem(UNSENT_KEY, JSON.stringify(unsent));
}

const QUOTE_KINDS: readonly QuoteRef['kind'][] = ['item', 'block', 'path'];

function isQuote(saved: unknown): saved is QuoteRef {
  if (typeof saved !== 'object' || saved === null) return false;
  const { kind, id, label } = saved as Partial<Record<keyof QuoteRef, unknown>>;
  return QUOTE_KINDS.some((each) => each === kind) && typeof id === 'string' && typeof label === 'string';
}

/** The quote over the field `field`, not sent; none where it holds none. */
export function unsentQuote(field: string): QuoteRef | null {
  const quote = readUnsent()[`${field}/quote`];
  return isQuote(quote) ? quote : null;
}

/** Keeps the quote over a field beside its words until it is sent or dropped, over what another tab keeps; none, nothing kept. */
export function keepUnsentQuote(field: string, quote: QuoteRef | null): void {
  const unsent = readUnsent();
  if (quote === null) delete unsent[`${field}/quote`];
  else unsent[`${field}/quote`] = quote;
  localStorage.setItem(UNSENT_KEY, JSON.stringify(unsent));
}

/**
 * A one-ask item's choice before its Send (F32.3): the option chosen, and whether its field,
 * Other's or a No's, stands open, when the field's words are the choice and the option is what the
 * field's cross gives back.
 */
export interface Choice {
  answer: string | null;
  typing: boolean;
}

function isChoice(saved: unknown): saved is Choice {
  if (typeof saved !== 'object' || saved === null) return false;
  const { answer, typing } = saved as Partial<Record<keyof Choice, unknown>>;
  return (answer === null || typeof answer === 'string') && typeof typing === 'boolean';
}

const CHOICE = '/choice';

/** What is chosen and not sent, by its block's key. */
export function unsentChoices(): Map<string, Choice> {
  const choices = new Map<string, Choice>();
  for (const [key, choice] of Object.entries(readUnsent())) {
    if (key.endsWith(CHOICE) && isChoice(choice)) choices.set(key.slice(0, -CHOICE.length), choice);
  }
  return choices;
}

/** Keeps a block's choice beside its fields' words until it is sent, over what another tab keeps; none, nothing kept. */
export function keepUnsentChoice(field: string, choice: Choice | null): void {
  const unsent = readUnsent();
  if (choice === null) delete unsent[`${field}${CHOICE}`];
  else unsent[`${field}${CHOICE}`] = choice;
  localStorage.setItem(UNSENT_KEY, JSON.stringify(unsent));
}

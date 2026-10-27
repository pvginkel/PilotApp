/**
 * What the browser remembers (F133): kept in its storage, nothing of it on the server. Unsent text
 * is kept under a key of its own, read when its field opens and written as it is typed.
 */

import { useSyncExternalStore } from 'react';

export const THEMES = ['system', 'light', 'dark'] as const;
export type Theme = (typeof THEMES)[number];

/** The project list's collapsible groups (F1.5, F1.7). */
export const GROUPS = ['others', 'finished'] as const;
export type Group = (typeof GROUPS)[number];

/**
 * The side panel's tabs: an open project's Chat and Documents (F38.1), a draft's Draft and
 * Documents (F46.3). The first is the one a panel opens on until the person picks another.
 */
export const PANEL_TABS = ['chat', 'draft', 'documents'] as const;
export type PanelTab = (typeof PANEL_TABS)[number];

/** A project's side panel as the person last left it: open or not, and its tab. */
export interface Panel {
  open: boolean;
  tab: PanelTab;
}

interface BrowserState {
  theme: Theme;
  /** The project last on screen, which the bare address opens (F1.6). */
  project: string | null;
  /** Each group's chevron as the person last set it: open or not. */
  chevrons: Record<Group, boolean>;
  /** Each project's side panel, by the project's id, once the person set it (F1.6, F38.1). */
  panels: Record<string, Panel>;
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
  };
}

function loadPanels(saved: unknown): Record<string, Panel> {
  if (typeof saved !== 'object' || saved === null) return {};
  const panels: Record<string, Panel> = {};
  for (const [projectId, panel] of Object.entries(saved as Record<string, unknown>)) {
    if (typeof panel !== 'object' || panel === null) continue;
    const { open, tab } = panel as Partial<Record<keyof Panel, unknown>>;
    panels[projectId] = { open: open === true, tab: PANEL_TABS.find((each) => each === tab) ?? PANEL_TABS[0] };
  }
  return panels;
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

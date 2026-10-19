/**
 * What the browser remembers (F133): kept in its storage, nothing of it on the server.
 */

import { useSyncExternalStore } from 'react';

export const THEMES = ['system', 'light', 'dark'] as const;
export type Theme = (typeof THEMES)[number];

interface BrowserState {
  theme: Theme;
}

const STORAGE_KEY = 'pilot';

function load(): BrowserState {
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<Record<keyof BrowserState, unknown>>;
  return {
    theme: THEMES.find((theme) => theme === saved.theme) ?? 'system',
  };
}

let state = load();
const listeners = new Set<() => void>();

export function browserState(): BrowserState {
  return state;
}

export function rememberInBrowser(change: Partial<BrowserState>): void {
  state = { ...state, ...change };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useBrowserState(): BrowserState {
  return useSyncExternalStore(subscribe, browserState);
}

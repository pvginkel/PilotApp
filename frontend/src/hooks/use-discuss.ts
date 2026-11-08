/**
 * Discuss (F39): one chat per project, whichever Discuss opens it (F39.4). Discuss on an item, a
 * block, a file's overlay or a session log opens the side panel on the Chat tab, on top, with what
 * it quotes in the composer, until the message carrying it is sent or the quote is dropped (F39.3);
 * the project's head has no Discuss (F39.2). In a draft, Discuss takes its definition chat in the
 * timeline's place instead (F46.1). Either asks for the focus in the composer's field. The quote is
 * kept by the project in the browser's storage, beside the composer's unsent words, until the
 * message carrying it is sent or it is dropped (F133): a reload finds it over the words it is about.
 */

import { createContext, useContext, useSyncExternalStore } from 'react';
import { keepUnsentQuote, unsentQuote } from '@/lib/browser-state';
import type { QuoteRef } from '@/lib/chat/quotes';

/** The project's composer's field, which keys its unsent words and its quote in the browser. */
export const composerField = (projectId: string): string => `chat/${projectId}`;

interface Discussed {
  /** What the composer quotes. */
  quote: QuoteRef | null;
  /** Discuss asked for the focus in the composer's field, which takes it once drawn. */
  focus: boolean;
}

let discussed: Record<string, Discussed> = {};
const listeners = new Set<() => void>();

/** The project's, read from the browser at the page's first look. */
function stateOf(projectId: string): Discussed {
  discussed[projectId] ??= { quote: unsentQuote(composerField(projectId)), focus: false };
  return discussed[projectId];
}

function update(projectId: string, change: Partial<Discussed>): void {
  const next = { ...stateOf(projectId), ...change };
  discussed = { ...discussed, [projectId]: next };
  if (change.quote !== undefined) keepUnsentQuote(composerField(projectId), next.quote);
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Puts `quote` in the project's composer, none dropping the one there, and asks for the focus in its field. */
export function discussIn(projectId: string, quote: QuoteRef | null): void {
  update(projectId, { quote, focus: true });
}

/** The composer's field took the focus Discuss asked for. */
export function focusTaken(projectId: string): void {
  update(projectId, { focus: false });
}

/** The project's composer's quote, whether Discuss asks for the focus in its field, and the quote's drop. */
export function useDiscussed(projectId: string) {
  const { quote, focus } = useSyncExternalStore(subscribe, () => stateOf(projectId));
  return {
    quote,
    focus,
    /** Drops `which` where it is still the composer's quote. */
    drop: (which: QuoteRef) => {
      if (stateOf(projectId).quote === which) update(projectId, { quote: null });
    },
  };
}

/** Discuss on a project's screens, which the project's route gives: the Chat tab on top, `quote` in its composer. */
export const DiscussContext = createContext<((quote: QuoteRef) => void) | null>(null);

export function useDiscuss(): (quote: QuoteRef) => void {
  return useContext(DiscussContext)!;
}

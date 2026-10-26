/**
 * Discuss (F39): one chat per project, whichever Discuss opens it (F39.4). Discuss on an item, a
 * block, a file's overlay or a session log opens the side panel on the Chat tab, on top, with what
 * it quotes in the composer, until the message carrying it is sent or the quote is dropped (F39.3);
 * the head's Discuss opens it with nothing quoted (F39.2). Either asks for the focus in the
 * composer's field. The quote is kept in the page, by the project, and nothing of it in the
 * browser's storage.
 */

import { createContext, useContext, useSyncExternalStore } from 'react';
import type { QuoteRef } from '@/lib/chat/quotes';

interface Discussed {
  /** What the composer quotes. */
  quote: QuoteRef | null;
  /** Discuss asked for the focus in the composer's field, which takes it once drawn. */
  focus: boolean;
}

const NONE: Discussed = { quote: null, focus: false };
let discussed: Record<string, Discussed> = {};
const listeners = new Set<() => void>();

function update(projectId: string, change: Partial<Discussed>): void {
  discussed = { ...discussed, [projectId]: { ...(discussed[projectId] ?? NONE), ...change } };
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
  const { quote, focus } = useSyncExternalStore(subscribe, () => discussed[projectId] ?? NONE);
  return {
    quote,
    focus,
    /** Drops `which` where it is still the composer's quote. */
    drop: (which: QuoteRef) => {
      if (discussed[projectId]?.quote === which) update(projectId, { quote: null });
    },
  };
}

/** Discuss on a project's screens, which the project's route gives: the Chat tab on top, `quote` in its composer. */
export const DiscussContext = createContext<((quote: QuoteRef) => void) | null>(null);

export function useDiscuss(): (quote: QuoteRef) => void {
  return useContext(DiscussContext)!;
}

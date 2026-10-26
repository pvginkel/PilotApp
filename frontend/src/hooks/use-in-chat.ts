/**
 * *In the chat* (F42.3): a block answered in the chat goes to the message that gave the answer. It
 * opens the side panel on the Chat tab, on top, with nothing quoted, as Discuss opens it; the tab
 * loads the chats before until the one holding the place, then scrolls to that message and flashes
 * it. The place is kept in the page, by the project, until the tab reaches it; each click puts it
 * afresh, so the same place is gone to again.
 */

import { createContext, useCallback, useContext, useSyncExternalStore } from 'react';
import type { components } from '@/lib/api/generated/types';

/** Where a block's answer was recorded in the chat: the chat, and its record's number (a block's `in_chat`). */
export type ChatPlace = components['schemas']['TimelineSchema.1fdd8ae.ChatPlaceSchema'];

let places: Record<string, ChatPlace | undefined> = {};
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function update(projectId: string, place: ChatPlace | undefined): void {
  places = { ...places, [projectId]: place };
  listeners.forEach((listener) => listener());
}

/** Puts the place the project's Chat tab goes to. */
export function goToChat(projectId: string, place: ChatPlace): void {
  update(projectId, { ...place });
}

/** The place the project's Chat tab goes to, none once reached, and its reach. */
export function useChatPlace(projectId: string) {
  const place = useSyncExternalStore(subscribe, () => places[projectId] ?? null);
  /** `which` was gone to: dropped where it is still the place. */
  const reached = useCallback(
    (which: ChatPlace) => {
      if (places[projectId] === which) update(projectId, undefined);
    },
    [projectId],
  );
  return { place, reached };
}

/** *In the chat* on a project's screens, which the project's route gives: the Chat tab on top, at the place. */
export const InChatContext = createContext<((place: ChatPlace) => void) | null>(null);

export function useInChat(): (place: ChatPlace) => void {
  return useContext(InChatContext)!;
}

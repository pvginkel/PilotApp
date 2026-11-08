/**
 * How far back a project's chat shows (F130.1): its first chat shown, kept in the page by the
 * project for the page's life, so that the chats loaded earlier show again once the reader is
 * back from another project or another tab; a reload starts from the latest again. Where a chat has
 * opened since the chat last showed, it shows the latest alone. A list the cache holds as the
 * chat opens may predate that chat, and while the read its opening makes is under way, what it
 * shows waits for that read before it says whether one opened. A chat that opens while it shows
 * comes in below.
 */

import { useEffect, useState } from 'react';
import type { Chat } from '@/hooks/use-chats';

interface Reach {
  /** The first chat shown. */
  from: string;
  /** The latest chat as the list stood while the chat last showed. */
  latest: string;
}

const reaches = new Map<string, Reach>();

/**
 * The first chat shown, by its place in `chats`, null while there is none, and its move; `reading`
 * while a read of the list is under way.
 */
export function useChatReach(projectId: string, chats: readonly Chat[] | null, reading: boolean) {
  const [left] = useState(() => reaches.get(projectId));
  const [from, setFrom] = useState<string | null>(null);
  // Whether the list in hand is one this chat can trust to hold every chat opened before it showed:
  // a read landed since, or the cache's with none under way.
  const [current, setCurrent] = useState(false);
  const latest = chats?.at(-1)?.id ?? null;

  let next = from;
  if (chats !== null && !current && !reading) {
    setCurrent(true);
    if (left !== undefined && latest !== left.latest) next = latest;
  }
  if (chats !== null && next === null) {
    const back = left !== undefined && latest === left.latest && chats.some((chat) => chat.id === left.from);
    next = back ? left.from : latest;
  }
  if (next !== from) setFrom(next);

  useEffect(() => {
    if (current && from !== null && latest !== null) reaches.set(projectId, { from, latest });
  }, [projectId, current, from, latest]);

  return {
    from: chats === null || next === null ? null : chats.findIndex((chat) => chat.id === next),
    setFrom: (index: number) => setFrom(chats![index]!.id),
  };
}

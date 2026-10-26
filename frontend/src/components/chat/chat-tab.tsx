/**
 * The side panel's Chat tab (F38, F40.3, F130.1): the project's latest chat, or with none open the
 * latest closed one, above its "Chat closed · <time>". "The chat before · <day>" at the top loads
 * that chat above what is in view and leaves the view where it is (the chat mockup's decision 11);
 * a chat that opens while the tab shows comes in below. Every viewer streams the chats it shows, so
 * another person's message and Pilot's reply come to them as to the sender (decision 13); the list
 * is read again on `project_changed`, which a chat's open and close and each move of its session
 * raise. Nothing stands in it while the list's read is under way, and "The chat did not load." while
 * its latest read failed (F113). Sticky scroll keeps a streaming reply in view while the reader is at
 * the bottom; only their own scrolling lets go. On a phone it is the same column (decision 12).
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronUp } from 'lucide-react';
import { useProjectChats } from '@/hooks/use-chats';
import { usePerson } from '@/hooks/use-self';
import { useStickyBottom } from '@/hooks/use-sticky-bottom';
import type { components } from '@/lib/api/generated/types';
import { day } from '@/lib/chat/format';
import { ChatEmptyState } from './chat-empty-state';
import { ChatSection } from './chat-section';
import { chatPeople } from './people';

type Member = components['schemas']['ProjectHeadSchema.e86ccd6.MemberSchema'];

/** The reader's own input, which lets go of the line *load more* keeps in place. */
const READER = ['wheel', 'touchstart', 'pointerdown', 'keydown'] as const;

export function ChatTab({ projectId, members }: { projectId: string; members: readonly Member[] }) {
  const read = useProjectChats(projectId);
  const person = usePerson();
  const people = useMemo(() => chatPeople(person, members), [person, members]);
  const chats = typeof read === 'string' ? null : read.chats;
  // The first chat shown, by its place in the list: the latest at the first read, so that a chat
  // opening later comes in below it.
  const [from, setFrom] = useState<number | null>(null);
  if (from === null && chats !== null) setFrom(Math.max(0, chats.length - 1));
  const container = useRef<HTMLDivElement>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const { unstick } = useStickyBottom(container, wrapper, 'chat');
  // While the chat before loads above, the line at the top of the view keeps its place, until the
  // reader scrolls: a chat's records land after the click, and its growth moves what is below.
  const anchor = useRef<{ element: Element; top: number } | null>(null);

  useEffect(() => {
    const box = container.current!;
    const observer = new ResizeObserver(() => {
      const held = anchor.current;
      if (held === null) return;
      if (!held.element.isConnected) {
        anchor.current = null;
        return;
      }
      const moved = held.element.getBoundingClientRect().top - box.getBoundingClientRect().top - held.top;
      if (Math.abs(moved) >= 1) box.scrollTop += moved;
    });
    observer.observe(wrapper.current!);
    const release = () => {
      anchor.current = null;
    };
    for (const event of READER) box.addEventListener(event, release, { passive: true });
    return () => {
      observer.disconnect();
      for (const event of READER) box.removeEventListener(event, release);
    };
  }, []);

  const shown = chats !== null && from !== null ? chats.slice(from) : [];
  const before = chats !== null && from !== null && from > 0 ? chats[from - 1] : undefined;

  const loadMore = () => {
    const box = container.current!;
    const top = box.getBoundingClientRect().top;
    const first = [...wrapper.current!.children].find((child) => child.tagName !== 'BUTTON' && child.getBoundingClientRect().bottom > top);
    anchor.current = first === undefined ? null : { element: first, top: first.getBoundingClientRect().top - top };
    unstick();
    setFrom(from! - 1);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="panel.chat">
      {/* The browser's own scroll anchoring off: it would move the view a second time. */}
      <div
        ref={container}
        className="relative min-h-0 flex-1 overflow-y-auto [overflow-anchor:none] [scrollbar-gutter:stable]"
        data-testid="chat.body"
      >
        <div ref={wrapper} className="flex min-h-full flex-col justify-end gap-4 px-3.5 pt-2 pb-4 text-[14px]" data-testid="chat">
          {read === 'failed' ? (
            <p className="mx-2 my-auto text-center text-[14px] text-muted-foreground" data-testid="panel.chat.failed">
              The chat did not load.
            </p>
          ) : (
            <>
              {before !== undefined && (
                <button
                  type="button"
                  onClick={loadMore}
                  className="mx-auto mt-1 inline-flex items-center gap-1.5 rounded-md border border-r-2 border-b-2 px-2.5 py-0.5 text-[12.5px] text-muted-foreground hover:bg-accent hover:text-foreground"
                  data-testid="chat.before"
                >
                  <ChevronUp className="size-3.5" aria-hidden />
                  The chat before · {day(before.opened_at)}
                </button>
              )}
              {chats?.length === 0 && <ChatEmptyState />}
              {shown.map((chat) => (
                <ChatSection key={chat.id} chat={chat} people={people} />
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

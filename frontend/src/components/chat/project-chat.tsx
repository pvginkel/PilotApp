/**
 * The project's chats where they stand (F38, F40.3, F130.1): the side panel's Chat tab, or, for a
 * draft, its definition chat in the timeline's place, the composer under it in the timeline's
 * column (F46.1; the mockup's `renderChat`, its home the page until Create). Either shows the
 * project's latest chat, or with none open the latest closed one, above its "Chat closed · <time>".
 * "The chat before · <day>" at the top loads that chat above what is in view and leaves the view
 * where it is (the chat mockup's decision 11); a chat that opens while it shows comes in below.
 * Every viewer streams the chats it shows, so another person's message and Pilot's reply come to
 * them as to the sender (decision 13); the list is read again on `project_changed`, which a chat's
 * open and close and each move of its session raise. Nothing stands in it while the list's read is
 * under way, "The chat did not load." while its latest read failed, and with no chat yet what to
 * ask, or in a draft "Tell Pilot what to manage" (F113). Sticky scroll keeps a streaming reply in
 * view while the reader is at the bottom; only their own scrolling lets go, and their message sent
 * from the composer under it, or a quote Discuss put there, goes back to the bottom. Shown at its
 * end, and not lying under the overlay, the chat is seen (F43). *In the chat* takes it to the
 * message that gave an answer (F42.3): the chats before loaded until the one holding it, the
 * pinning let go, the message scrolled into the middle of the view and flashed, and kept in its
 * place, as *load more* keeps the line in view, until the reader scrolls. On a phone it is the same
 * column (decision 12).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronUp } from 'lucide-react';
import { useFlashes } from '@/components/timeline/flash';
import { useChatSeen, useProjectChats } from '@/hooks/use-chats';
import { useChatPlace, type ChatPlace } from '@/hooks/use-in-chat';
import { usePerson } from '@/hooks/use-self';
import { useStickyBottom } from '@/hooks/use-sticky-bottom';
import type { components } from '@/lib/api/generated/types';
import { day } from '@/lib/chat/format';
import { cn } from '@/lib/utils';
import { ChatEmptyState, type ChatHome } from './chat-empty-state';
import { ChatSection, messageKey } from './chat-section';
import { Composer } from './composer';
import { chatPeople } from './people';

type Member = components['schemas']['ProjectHeadSchema.e86ccd6.MemberSchema'];

/** The reader's own input, which lets go of the line *load more* keeps in place. */
const READER = ['wheel', 'touchstart', 'pointerdown', 'keydown'] as const;

interface ProjectChatProps {
  projectId: string;
  members: readonly Member[];
  home: ChatHome;
  /** It lies under the overlay and its backdrop: it takes no focus. */
  covered: boolean;
}

export function ProjectChat({ projectId, members, home, covered }: ProjectChatProps) {
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
  const { stick, unstick, stuck } = useStickyBottom(container, wrapper, 'chat');
  const { place, reached } = useChatPlace(projectId);
  // On its way to a place the chat is not shown at its end, however the view stands.
  useChatSeen(projectId, !covered && stuck && place === null && chats !== null, typeof read !== 'string' && read.unread);
  const { fresh: flashing, flashed, flash } = useFlashes();
  // The chats before load until the one holding the place.
  const holding = place === null || chats === null ? -1 : chats.findIndex((chat) => chat.id === place.chat);
  if (from !== null && holding >= 0 && holding < from) setFrom(holding);
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

  useEffect(() => {
    if (place !== null) unstick();
  }, [place, unstick]);
  // Pinned to the end again, the end rules.
  useEffect(() => {
    if (stuck) anchor.current = null;
  }, [stuck]);

  const gone = useRef<ChatPlace | null>(null);
  const found = useCallback(
    (message: HTMLElement, seq: number) => {
      if (place === null || gone.current === place) return;
      gone.current = place;
      const box = container.current!;
      const offset = () => message.getBoundingClientRect().top - box.getBoundingClientRect().top;
      unstick();
      box.scrollTop += offset() - Math.max(0, (box.clientHeight - message.offsetHeight) / 2);
      anchor.current = { element: message, top: offset() };
      flash(messageKey(place.chat, seq));
      reached(place);
    },
    [place, unstick, flash, reached],
  );

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

  const toEnd = useCallback(() => {
    anchor.current = null;
    stick();
  }, [stick]);

  return (
    <div className="flex min-h-0 flex-1 flex-col" inert={covered} data-testid={home === 'feed' ? 'project.chat' : 'panel.chat'}>
      {/* The browser's own scroll anchoring off: it would move the view a second time. */}
      <div
        ref={container}
        className="relative min-h-0 flex-1 overflow-y-auto [overflow-anchor:none] [scrollbar-gutter:stable]"
        data-testid="chat.body"
      >
        <div
          ref={wrapper}
          className={cn(
            'flex min-h-full flex-col justify-end gap-4',
            home === 'feed'
              ? 'mx-auto w-full max-w-(--column) px-6 py-5 text-[15px] [--person-width:75%] max-[900px]:px-3'
              : 'px-3.5 pt-2 pb-4 text-[14px]',
          )}
          data-testid="chat"
        >
          {read === 'failed' ? (
            <p className="mx-2 my-auto text-center text-[14px] text-muted-foreground" data-testid="chat.failed">
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
              {chats?.length === 0 && <ChatEmptyState home={home} />}
              {shown.map((chat) => (
                <ChatSection
                  key={chat.id}
                  chat={chat}
                  people={people}
                  goTo={place?.chat === chat.id ? place.seq : undefined}
                  onFound={found}
                  flashing={flashing}
                  onFlashed={flashed}
                />
              ))}
            </>
          )}
        </div>
      </div>
      <Composer
        projectId={projectId}
        home={home}
        answering={chats?.at(-1)?.answering ?? false}
        onSent={toEnd}
        onDiscussed={toEnd}
      />
    </div>
  );
}

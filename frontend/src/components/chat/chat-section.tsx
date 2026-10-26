/**
 * One chat as the Chat tab shows it (F38.2, F40): its records streamed from the first while it
 * shows (F40.3), as the view builds them — each person's message, Pilot's reply to it, the cue while
 * Pilot answers — a date divider over its first message and over each the day turns at, the
 * phantom on its turn in flight, and "Chat closed · <time>" where it closed (F130.1). What comes live
 * fades in, what loads does not. A turn its records leave open ended when Pilot no longer answers.
 * Asked to go to one of its records, it finds the message of the turn holding it once its stream has
 * read that far: the latest message at or before it (F42.3).
 */

import { Fragment, useLayoutEffect, useMemo, useRef } from 'react';
import { useSseContext } from '@/contexts/sse-context';
import { useChatStream } from '@/hooks/use-chat-stream';
import type { Chat } from '@/hooks/use-chats';
import { useSessionTransport } from '@/hooks/use-session-transport';
import { day, dayKey } from '@/lib/chat/format';
import { buildChatView } from '@/lib/chat/view';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';
import type { ChatPeople } from './people';
import { PersonMessage } from './person-message';
import { PilotReply } from './pilot-reply';
import { DateDivider, SessionSeparator } from './session-separator';

interface ChatSectionProps {
  chat: Chat;
  people: ChatPeople;
  /** The number of a record of the chat to go to: `onFound` is given the message of its turn, and that message's number. */
  goTo?: number;
  onFound?: (message: HTMLElement, seq: number) => void;
  /** The messages flashing, by `messageKey`, and the end of one's flash. */
  flashing?: ReadonlySet<string>;
  onFlashed?: (key: string) => void;
}

/** The key a message of a chat flashes by. */
export const messageKey = (chatId: string, seq: number) => `${chatId}:${seq}`;

export function ChatSection({ chat, people, goTo, onFound, flashing, onFlashed }: ChatSectionProps) {
  const { isConnected } = useSseContext();
  const stream = useChatStream(useSessionTransport(), chat.id);
  useUiStateInstrumentation('chat.section', {
    isLoading: stream.status === 'connecting' || stream.status === 'dropped',
    getReadyMetadata: () => ({ chat: chat.id, live: isConnected, lastSeq: stream.lastSeq }),
  });
  const items = useMemo(
    () => buildChatView(chat.id, stream.records, { running: chat.answering }),
    [chat.id, stream.records, chat.answering],
  );
  const last = items.at(-1);
  const fresh = (seq: number) => stream.liveFrom !== null && seq >= stream.liveFrom;

  let target: number | null = null;
  if (goTo !== undefined && stream.lastSeq >= goTo) {
    for (const item of items) {
      if (item.kind === 'turn' && item.turn.person !== undefined && item.turn.person.seq <= goTo) target = item.turn.person.seq;
    }
  }
  const targetMessage = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    if (target !== null) onFound?.(targetMessage.current!, target);
  }, [target, onFound]);

  // A turn's day, by its message's time where it has one: the turns a divider stands over.
  const dividers = new Set<string>();
  let shownDay: string | null = null;
  for (const item of items) {
    if (item.kind !== 'turn') continue;
    const turnDay = dayKey(item.turn.person?.at ?? item.turn.startedAt);
    if (turnDay !== shownDay) dividers.add(item.key);
    shownDay = turnDay;
  }

  return items.map((item) => {
    if (item.kind === 'closed') return <SessionSeparator key={item.key} at={item.at} />;
    const { turn } = item;
    const { person } = turn;
    const at = person?.at ?? turn.startedAt;
    const replied = turn.steps.length > 0 || turn.state !== 'done' || turn.comingUp !== null;
    return (
      <Fragment key={item.key}>
        {dividers.has(item.key) && <DateDivider label={day(at)} />}
        {person && (
          <PersonMessage
            ref={person.seq === target ? targetMessage : undefined}
            record={person}
            fresh={fresh(person.seq)}
            people={people}
            flash={flashing?.has(messageKey(chat.id, person.seq))}
            onFlashed={() => onFlashed?.(messageKey(chat.id, person.seq))}
          />
        )}
        {replied && (
          <PilotReply
            turn={turn}
            phantom={item === last && turn.state === 'running' ? stream.phantom : null}
            liveFrom={stream.liveFrom}
            streamed={stream.streamed}
          />
        )}
      </Fragment>
    );
  });
}

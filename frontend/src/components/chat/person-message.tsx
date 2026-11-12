/**
 * A person's message (F38.2): on the right in the primary's tint, the opening prompt's bubble a
 * step deeper, its tail at the foot (mockup M3), leaving at least 9 % of the
 * column on its left, the time and the avatar under it, and another person's name before the time
 * (the chat mockup's decision 13). A quote it opens with stands over it, and one inside it is a chip
 * where it stands (F39.3). Its words show as written, ticket ids, repos and environments linked
 * (F91, F93). Gone to by *In the chat*, it flashes (F42.3): its words, or a message of quotes alone
 * whole. A message sent from this page stands so from its Send, before its record, which has its
 * number, takes its place (use-stand-ins.ts).
 */

import { Fragment, type AnimationEvent, type Ref } from 'react';
import { LinkedText } from '@/components/shared/linked-text';
import { Avatar } from '@/components/shared/avatar';
import { Time } from '@/components/shared/time';
import type { StandIn } from '@/hooks/use-stand-ins';
import { day, dayKey } from '@/lib/chat/format';
import { splitQuotes, type QuotePart, type QuoteRef } from '@/lib/chat/quotes';
import type { SendRecord } from '@/lib/chat/records';
import { cn } from '@/lib/utils';
import type { ChatPeople } from './people';
import { QuoteChip, QuoteLine } from './quote-chip';
import { DateDivider } from './session-separator';

/** The quotes a text opens with, and the rest, trimmed. */
function leadOf(text: string): { lead: QuoteRef[]; rest: QuotePart[] } {
  const rest = splitQuotes(text);
  const lead: QuoteRef[] = [];
  while (rest[0]?.type === 'quote' || (rest[0]?.type === 'text' && rest[0].text.trim() === '' && rest[1]?.type === 'quote')) {
    const part = rest.shift()!;
    if (part.type === 'quote') lead.push(part.quote);
  }
  const first = rest[0];
  if (first?.type === 'text') rest[0] = { type: 'text', text: first.text.trimStart() };
  const last = rest.at(-1);
  if (last?.type === 'text') rest[rest.length - 1] = { type: 'text', text: last.text.trimEnd() };
  return { lead, rest: rest.filter((part) => part.type === 'quote' || part.text !== '') };
}

interface PersonMessageProps {
  /** The message's record; a stand-in's has no number. */
  record: Pick<SendRecord, 'message' | 'author' | 'at'> & { seq?: number };
  fresh: boolean;
  people: ChatPeople;
  /** It flashes, until `onFlashed`. */
  flash?: boolean;
  onFlashed?: () => void;
  ref?: Ref<HTMLElement>;
}

export function PersonMessage({ record, fresh, people, flash = false, onFlashed, ref }: PersonMessageProps) {
  const { lead, rest } = leadOf(record.message);
  const author = record.author === null ? null : people.who(record.author);
  const flashed = (event: AnimationEvent) => {
    if (event.animationName === 'fresh') onFlashed?.();
  };
  return (
    <section
      ref={ref}
      className={cn(
        'flex max-w-(--person-width,91%) min-w-0 flex-col items-end self-end',
        fresh && 'animate-fade-in opacity-0',
        flash && rest.length === 0 && 'flash',
      )}
      onAnimationEnd={flashed}
      data-seq={record.seq}
      data-stand-in={record.seq === undefined || undefined}
      data-testid="chat.person"
    >
      {lead.map((quote, index) => (
        <QuoteLine key={index} quote={quote} />
      ))}
      {rest.length > 0 && (
        <div
          className={cn(
            'rounded-[14px_14px_4px] bg-bubble px-3 py-2 wrap-anywhere whitespace-pre-wrap',
            flash && 'flash',
          )}
          data-testid="chat.person.text"
        >
          {rest.map((part, index) =>
            part.type === 'text' ? (
              <LinkedText key={index} text={part.text} />
            ) : (
              <QuoteChip key={index} quote={part.quote} label={part.quote.label} />
            ),
          )}
        </div>
      )}
      <div className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="chat.person.end">
        {author !== null && record.author !== people.me && <span data-testid="chat.person.name">{author.name}</span>}
        <Time at={record.at} format="clock" />
        {author !== null && <Avatar who={author} size="xs" />}
      </div>
    </section>
  );
}

interface StandInsProps {
  standIns: readonly StandIn[];
  people: ChatPeople;
  /** The day of the message they stand after, by `dayKey`; none where they open a chat. */
  after: string | null;
}

/** The person's messages whose records the chat does not show yet, as the records will stand: a date divider over one the day turns at. */
export function StandIns({ standIns, people, after }: StandInsProps) {
  let shownDay = after;
  return standIns.map((standIn) => {
    const turned = dayKey(standIn.at) !== shownDay;
    shownDay = dayKey(standIn.at);
    return (
      <Fragment key={standIn.id}>
        {turned && <DateDivider label={day(standIn.at)} />}
        <PersonMessage record={{ message: standIn.message, author: people.me, at: standIn.at }} fresh={false} people={people} />
      </Fragment>
    );
  });
}

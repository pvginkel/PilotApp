/**
 * A person's message (F38.2): on the right in the primary's tint, leaving at least 9 % of the
 * column on its left, the time and the avatar under it, and another person's name before the time
 * (the chat mockup's decision 13). A quote it opens with stands over it, and one inside it is a chip
 * where it stands (F39.3). Its words show as written, ticket ids, repos and environments linked
 * (F91, F93).
 */

import { LinkedText } from '@/components/shared/linked-text';
import { Avatar } from '@/components/shared/avatar';
import { Time } from '@/components/shared/time';
import { splitQuotes, type QuotePart, type QuoteRef } from '@/lib/chat/quotes';
import type { SendRecord } from '@/lib/chat/records';
import { cn } from '@/lib/utils';
import type { ChatPeople } from './people';
import { QuoteChip, QuoteLine } from './quote-chip';

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

export function PersonMessage({ record, fresh, people }: { record: SendRecord; fresh: boolean; people: ChatPeople }) {
  const { lead, rest } = leadOf(record.message);
  const author = record.author === null ? null : people.who(record.author);
  return (
    <section
      className={cn('flex max-w-[91%] min-w-0 flex-col items-end self-end', fresh && 'animate-fade-in opacity-0')}
      data-seq={record.seq}
      data-testid="chat.person"
    >
      {lead.map((quote, index) => (
        <QuoteLine key={index} quote={quote} />
      ))}
      {rest.length > 0 && (
        <div
          className="rounded-lg border border-primary-muted-foreground/20 bg-primary-muted px-3 py-2 wrap-anywhere whitespace-pre-wrap"
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

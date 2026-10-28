/**
 * An item on the timeline. A prose item open is its head (F12), its title and its text, the prose
 * drawn as GFM (F29.1), the prose before its first block folding when long (F12.2), a one-ask
 * item's block answered in its place (F19.1, F20, F21) and a notice's Read under its text (F23),
 * and Pilot's dots at its end while Pilot writes it (F35); a confirmation is a card of its own
 * (F22), a short document stands inline (F24.1), and a larger one and a review leave a card
 * (F24.2, F25.1). A registered document whose writer Pilot asked says so under its title (F86.8).
 * Its attachments follow its text (F17.5). An urgent one is tinted (F10.1), and one
 * whose latest save is held shows its last published text with a dashed border, a concept (F78), and
 * a registered document awaiting its read is muted (F85.1). A
 * work item open is its session's (work.tsx, F26). Done, an item is its line (F13.1, F13.2), with
 * Open (F13.3), its attachments' indicator (F13.6), Undo while the record offers it (F14.1) and
 * Discuss (F13.4), and *In the chat* after a one-ask item's answer given in the chat (F42.3); a
 * work item's is quieter, its Open the session log (F13.5, F26.6), and a job's an Undo withdrew
 * says so (F14.1).
 */

import type { AnimationEvent, ReactNode } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import { Check, FileText, ScrollText, StickyNote, Undo2, X } from 'lucide-react';
import { DiscussButton } from '@/components/chat/discuss-button';
import { quoteOfItem } from '@/components/chat/discuss-quotes';
import { InChatButton } from '@/components/chat/in-chat-button';
import { Fold } from '@/components/shared/fold';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Time } from '@/components/shared/time';
import { Attachments, LineAttachments } from '@/components/timeline/attachments';
import { Block } from '@/components/timeline/block';
import { Confirmation } from '@/components/timeline/confirmation';
import { DocumentCard, InlineDocument } from '@/components/timeline/document';
import { isCard } from '@/components/timeline/document-state';
import { ItemHead } from '@/components/timeline/item-head';
import { kindOf } from '@/components/timeline/kinds';
import { UserAvatar } from '@/components/timeline/user-avatar';
import { WorkItem } from '@/components/timeline/work';
import { WriterAsked } from '@/components/timeline/writer-asked';
import { PilotWriting } from '@/components/timeline/writing';
import { useRead, useUndo } from '@/hooks/use-marks';
import { useArchived } from '@/hooks/use-projects';
import { blocksOf, isProse, titleOf, type BodyPart, type TimelineItem, type TimelineUser } from '@/hooks/use-timeline';
import { usePerson } from '@/hooks/use-self';
import { cn } from '@/lib/utils';
import { workClosedLabel } from '@/lib/utils/status-labels';

interface ItemProps {
  item: TimelineItem;
  /** Newly arrived: it flashes once. */
  fresh: boolean;
  onFlashed: () => void;
}

export function Item({ item, fresh, onFlashed }: ItemProps) {
  const done = item.done !== null;
  const flashed = (event: AnimationEvent) => event.target === event.currentTarget && onFlashed();
  return (
    <article
      className={cn(
        'item',
        done ? 'collapsed' : 'open',
        item.kind === 'confirmation' && 'confirm',
        done && item.kind === 'work' && 'quiet',
        !done && item.concept && 'concept',
        !done && item.awaiting_read && 'awaiting',
        !done && item.urgent && 'urgent',
        fresh && 'fresh',
      )}
      onAnimationEnd={flashed}
      data-testid="timeline.item"
      data-item-id={item.id}
      data-kind={item.kind}
      data-state={done ? 'done' : 'open'}
      data-concept={item.concept}
    >
      {done ? <DoneLine item={item} /> : <OpenItem item={item} />}
    </article>
  );
}

function OpenItem({ item }: { item: TimelineItem }) {
  if (item.kind === 'work') return <WorkItem item={item} />;
  if (item.kind === 'confirmation') return <Confirmation item={item} />;
  if (isCard(item)) return <DocumentCard item={item} />;
  if (item.kind === 'document') return <InlineDocument item={item} />;
  return (
    <div className="item-body">
      <ItemHead item={item} />
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      <WriterAsked item={item} />
      {/* The API gives every prose item but the opening its text. */}
      <ItemText body={item.body!} ask={askOf(item)} />
      <Attachments item={item} />
      {item.writing && <PilotWriting />}
    </div>
  );
}

/** What an open item asks, answered in place: a one-ask item's one block, a notice's Read. */
function askOf(item: TimelineItem): ReactNode {
  switch (item.kind) {
    case 'decision':
    case 'question':
    case 'action':
      return <Block item={item} block={blocksOf(item)[0]} solo />;
    case 'notice':
      return <Read item={item} />;
    default:
      return null;
  }
}

/**
 * A notice's one button, its own state: nothing goes back to a session (F23.1); disabled while the
 * project is archived, which the API refuses until Bring back (D012).
 */
function Read({ item }: { item: TimelineItem }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const { mark, pending } = useRead(item.id);
  const archived = useArchived(projectId);
  return (
    <div className="item-actions">
      <button type="button" className="btn btn-primary" onClick={mark} disabled={pending || archived} data-testid="timeline.item.read">
        <Check className="icon" aria-hidden="true" />
        Read
      </button>
    </div>
  );
}

/** The prose before the first block folds, the ask stands in that block's place, and what comes after shows whole. */
function ItemText({ body, ask }: { body: BodyPart[]; ask: ReactNode }) {
  const first = body.findIndex((part) => part.type === 'block');
  const lead = (first < 0 ? body : body.slice(0, first)).filter(isProse);
  const after = (first < 0 ? [] : body.slice(first + 1)).filter(isProse);
  return (
    <>
      {lead.length > 0 && (
        <Fold testId="timeline.item.text">
          {lead.map((part, index) => (
            <Markdown key={index} text={part.markdown} />
          ))}
        </Fold>
      )}
      {ask}
      {after.map((part, index) => (
        <div key={index} className="item-after">
          <Markdown text={part.markdown} />
        </div>
      ))}
    </>
  );
}

/** One ask in an item of its own: its line shows the person's answer under its title. */
const ONE_ASK = new Set<TimelineItem['kind']>(['decision', 'confirmation', 'question', 'action']);

interface Said {
  by: TimelineUser;
  words: string;
  note: string | null;
}

/**
 * A person's answer to a one-ask item, and its note; never what Pilot did. A confirmation's Yes or
 * No is no words: only its reason is.
 */
function saidIn(item: TimelineItem): Said | null {
  if (!ONE_ASK.has(item.kind)) return null;
  const [block] = blocksOf(item);
  if (block === undefined || block.by === null || block.by.kind === 'agent') return null;
  const words =
    item.kind === 'confirmation' || block.answer === null
      ? ''
      : block.answer === 'deferred'
        ? // The API gives a deferred block its deferral; a title of none is the project's end.
          `Deferred to ${block.deferral!.title ?? "the project's end"}`
        : block.answer;
  if (words === '' && block.note === null) return null;
  return { by: block.by, words, note: block.note };
}

/** Where a one-ask item's answer given in the chat was recorded, which *In the chat* goes to. */
function inChatOf(item: TimelineItem) {
  if (!ONE_ASK.has(item.kind)) return null;
  const [block] = blocksOf(item);
  return block?.in_chat ?? null;
}

/**
 * The same line for every kind: its icon, its title, Open, its attachments' indicator, Undo while
 * the record offers it, Discuss, and when it was done; under the title the person's answer to a one-ask item with its note, the other
 * person's after their avatar, and *In the chat* after it, kept whole, where it was given in the
 * chat; under a job's title that an Undo withdrew it (F14.1). A confirmation's Yes leads it with a
 * green check, its No with a red cross (F22.5). It does not expand.
 */
function DoneLine({ item }: { item: TimelineItem }) {
  const me = usePerson();
  const title = titleOf(item);
  const said = saidIn(item);
  const place = inChatOf(item);
  // An item's done line is drawn only once it is done.
  const done = item.done!;
  const closed = item.kind === 'work' ? workClosedLabel(done.cause) : null;
  return (
    <div className="line" data-testid="timeline.line">
      <LineLead item={item} />
      <span className="title" title={title} data-testid="timeline.line.title">
        <LinkedText text={title} />
      </span>
      <Open item={item} />
      <LineAttachments item={item} />
      {done.undo && <Undo item={item} />}
      <DiscussButton quote={quoteOfItem(item)} testId="timeline.line.discuss" />
      <Time at={done.at} format="clock" testId="timeline.line.time" />
      {(said || place) && (
        <span className="said" data-testid="timeline.line.said">
          {said && (
            <span className="said-text" title={[said.words, said.note].filter(Boolean).join(' · ')}>
              {said.by.handle !== me.handle && <UserAvatar user={said.by} size="xs" />}
              {said.words && <LinkedText text={said.words} />}
              {said.words && said.note && ' · '}
              {said.note && (
                <span className="note" data-testid="timeline.line.note">
                  <StickyNote className="icon" aria-hidden="true" />
                  <LinkedText text={said.note} />
                </span>
              )}
            </span>
          )}
          {place && <InChatButton place={place} testId="timeline.line.in-chat" />}
        </span>
      )}
      {closed !== null && (
        <span className="said" data-testid="timeline.line.closed">
          <span className="said-text">{closed}</span>
        </span>
      )}
    </div>
  );
}

/** The line's icon: its kind's, or a confirmation's answer. */
function LineLead({ item }: { item: TimelineItem }) {
  const answer = item.kind === 'confirmation' ? blocksOf(item)[0].answer : null;
  if (answer === 'Yes' || answer === 'No') {
    const Icon = answer === 'Yes' ? Check : X;
    return (
      <span className={cn('kind-icon', answer === 'Yes' ? 'yes' : 'no')} title={answer} data-testid="timeline.line.kind">
        <Icon className="icon" aria-hidden="true" />
      </span>
    );
  }
  const { icon: Icon } = kindOf(item);
  return (
    <span className="kind-icon" data-testid="timeline.line.kind">
      <Icon className="icon" aria-hidden="true" />
    </span>
  );
}

/**
 * Open: the item's document in the overlay, as it was done (F13.3), at the document's address; a
 * work item's session log, at its session's (F26.6).
 */
function Open({ item }: { item: TimelineItem }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  if (item.kind === 'work') {
    return (
      <Link
        to="/projects/$projectId/sessions/$sessionId"
        params={{ projectId, sessionId: item.id }}
        className="btn btn-ghost btn-sm btn-icon"
        title="Open the session log"
        aria-label="Open"
        data-testid="timeline.line.open"
      >
        <ScrollText className="icon" aria-hidden="true" />
      </Link>
    );
  }
  return (
    <Link
      to="/projects/$projectId/documents/$documentId"
      params={{ projectId, documentId: item.id }}
      className="btn btn-ghost btn-sm btn-icon"
      title="Open the document"
      aria-label="Open"
      data-testid="timeline.line.open"
    >
      <FileText className="icon" aria-hidden="true" />
    </Link>
  );
}

/** Undo, whoever answered, until a session has taken the answer (F14.1). */
function Undo({ item }: { item: TimelineItem }) {
  const { mark, pending } = useUndo(item.id);
  return (
    <button
      type="button"
      className="btn btn-ghost btn-sm btn-icon"
      onClick={mark}
      disabled={pending}
      title="Undo, until a session has taken it"
      aria-label="Undo"
      data-testid="timeline.line.undo"
    >
      <Undo2 className="icon" aria-hidden="true" />
    </button>
  );
}

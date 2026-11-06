/**
 * An item on the timeline. A prose item open is its head (F12), its title and its text, the prose
 * drawn as GFM (F29.1), the prose before its first block folding when long (F12.2), a one-ask
 * item's block answered in its place (F19.1, F20, F21) and a notice's Read under its text (F23),
 * and Pilot's dots at its end while Pilot writes it (F35); a confirmation is a card of its own
 * (F22), a short document stands inline (F24.1), and a larger one and a review leave a card
 * (F24.2, F25.1); the archive question is its two buttons (F5.6). A one-ask item whose writer Pilot
 * asked about its block carries the block's mark in its head (F52.2; writer-asked.tsx).
 * Its attachments follow its text (F17.5). An urgent one is tinted (F10.1), and one
 * whose latest save is held shows its last published text with a dashed border, a concept (F78). A
 * work item open is its session's (work.tsx, F26). An item Pilot is working on is one line in its
 * place, its kind's icon a dashed circle, what Pilot does on it its button (F13.7, F12.1, F24.1). Done, an item is its line (F13.1, F13.2), its
 * title opening what is behind it, with its attachments' indicator (F13.6) and *In the chat* after a
 * one-ask item's answer given in the chat (F42.3), and its actions under the mouse (F13.8): Open
 * (F13.3), Undo while the record offers it (F14.1) and Discuss (F13.4); a work item's is quieter,
 * its Open the session log (F13.5, F26.6). Pilot's job on an item shows on it, its line's or its
 * head's (job.tsx, F59.1). A wait open
 * is its own (wait.tsx, F27); done, its line has nothing behind it, no Open and no Undo, and the note
 * Pilot closed it with under its title (F27.4). On a phone the line has Undo alone among its actions,
 * and a tap on it opens what its title opens, as a view whose head carries Discuss, or, on a line
 * with nothing behind it, a menu of its actions under it, its job and Discuss (F13.9).
 */

import { useCallback, useState, type AnimationEvent, type MouseEvent, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from '@tanstack/react-router';
import { Check, CircleDashed, FileText, MessagesSquare, ScrollText, StickyNote, Undo2, X } from 'lucide-react';
import { DiscussButton } from '@/components/chat/discuss-button';
import { quoteOfItem } from '@/components/chat/discuss-quotes';
import { InChatButton } from '@/components/chat/in-chat-button';
import { Fold } from '@/components/shared/fold';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Time } from '@/components/shared/time';
import { ArchiveQuestion } from '@/components/timeline/archive-question';
import { Attachments, LineAttachments } from '@/components/timeline/attachments';
import { Block } from '@/components/timeline/block';
import { Confirmation } from '@/components/timeline/confirmation';
import { DocumentCard, InlineDocument } from '@/components/timeline/document';
import { isCard } from '@/components/timeline/document-state';
import { ItemHead } from '@/components/timeline/item-head';
import { JobButton, JobMark, JobMenuRow } from '@/components/timeline/job';
import { kindOf } from '@/components/timeline/kinds';
import { PilotsButton } from '@/components/timeline/pilots';
import { UserAvatar } from '@/components/timeline/user-avatar';
import { WaitItem } from '@/components/timeline/wait';
import { WorkItem } from '@/components/timeline/work';
import { PilotWriting } from '@/components/timeline/writing';
import { useDiscuss } from '@/hooks/use-discuss';
import { useDismiss } from '@/hooks/use-dismiss';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import { useRead, useUndo } from '@/hooks/use-marks';
import { usePhone } from '@/hooks/use-phone';
import { useArchived } from '@/hooks/use-projects';
import { blocksOf, isProse, titleOf, type BodyPart, type PilotsWork, type TimelineItem, type TimelineUser } from '@/hooks/use-timeline';
import { usePerson } from '@/hooks/use-self';
import { cn } from '@/lib/utils';
import { jobForm } from '@/lib/utils/status-labels';

interface ItemProps {
  item: TimelineItem;
  /** Newly arrived: it flashes once. */
  fresh: boolean;
  onFlashed: () => void;
}

export function Item({ item, fresh, onFlashed }: ItemProps) {
  const done = item.done !== null;
  // The API gives what Pilot does only on an open item.
  const pilots = item.pilots_work;
  const open = !done && pilots === null;
  const flashed = (event: AnimationEvent) => event.target === event.currentTarget && onFlashed();
  return (
    <article
      className={cn(
        'item',
        open ? 'open' : 'collapsed',
        pilots !== null && 'pilots',
        item.kind === 'confirmation' && 'confirm',
        done && item.kind === 'work' && 'quiet',
        open && item.concept && 'concept',
        open && item.urgent && 'urgent',
        fresh && 'fresh',
      )}
      onAnimationEnd={flashed}
      data-testid="timeline.item"
      data-item-id={item.id}
      data-kind={item.kind}
      data-state={done ? 'done' : pilots !== null ? 'pilots' : 'open'}
      data-concept={item.concept}
    >
      {done ? <DoneLine item={item} /> : pilots !== null ? <PilotsLine item={item} pilots={pilots} /> : <OpenItem item={item} />}
    </article>
  );
}

function OpenItem({ item }: { item: TimelineItem }) {
  if (item.kind === 'work') return <WorkItem item={item} />;
  if (item.form === 'wait') return <WaitItem item={item} />;
  if (item.kind === 'confirmation') return <Confirmation item={item} />;
  if (item.kind === 'archive_question') return <ArchiveQuestion item={item} />;
  if (isCard(item)) return <DocumentCard item={item} />;
  if (item.kind === 'document') return <InlineDocument item={item} />;
  return (
    <div className="item-body">
      <ItemHead item={item} asked={blocksOf(item).some((block) => block.writer_asked)} />
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
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
const ONE_ASK = new Set<TimelineItem['kind']>(['decision', 'confirmation', 'question', 'action', 'archive_question']);

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
 * The same line for every kind: its icon, its title, a link to what is behind it where something
 * is, its actions, its attachments' indicator and when it was done; under the title the person's
 * answer to a one-ask item with its note, the other person's after their avatar, and *In the chat*
 * after it, kept whole, where it was given in the chat; under a wait's the note Pilot closed it
 * with (F27.4). A confirmation's Yes leads it with a green check, its No with a red cross (F22.5).
 * It does not expand. Its actions, the mark of Pilot's job on it once the job ended, Open where
 * something is behind it, Undo while the record offers it and Discuss, show while the mouse is on
 * it or the focus in it, and always where nothing hovers (timeline.css, F13.8); a job not ended
 * stands at its end beside the time, shown always (F59.1). On a phone the job's mark, Open and
 * Discuss leave it, and a tap on it anywhere but on a control of its own opens what its title
 * opens, or a wait's menu (F13.9).
 */
function DoneLine({ item }: { item: TimelineItem }) {
  const phone = usePhone();
  const openView = useOpenLine(item);
  if (!phone) return <Line item={item} />;
  return item.form === 'wait' ? <MenuLine item={item} /> : <Line item={item} onTap={openView} />;
}

/** Whether a tap on a line fell on a control of its own, which acts alone. */
const onControl = (event: MouseEvent) => (event.target as Element).closest('a, button, [role="menu"]') !== null;

/**
 * A phone's line with nothing behind it, a wait's: a tap on it opens the menu of its actions under
 * it, as the mockup's `lineMenu()` offers them, Pilot's job on it where one shows and Discuss, never
 * Undo, and a tap on it again or anywhere else closes the menu (F13.9).
 */
function MenuLine({ item }: { item: TimelineItem }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const anchor = useDismiss('menu', open, close);
  const discuss = useDiscuss();
  return (
    <div ref={anchor}>
      <Line item={item} onTap={(event) => !onControl(event) && setOpen(!open)} />
      {open && (
        <div className="line-menu" role="menu" aria-label="The line’s actions" data-testid="timeline.line.menu">
          {item.job !== null && <JobMenuRow job={item.job} onOpen={close} />}
          <button
            type="button"
            role="menuitem"
            className="btn btn-ghost btn-sm"
            onClick={() => {
              close();
              discuss(quoteOfItem(item));
            }}
            data-testid="timeline.line.menu.discuss"
          >
            <MessagesSquare className="icon" aria-hidden="true" />
            Discuss
          </button>
        </div>
      )}
    </div>
  );
}

function Line({ item, onTap }: { item: TimelineItem; onTap?: (event: MouseEvent) => void }) {
  const me = usePerson();
  const phone = usePhone();
  const title = titleOf(item);
  const said = saidIn(item);
  const place = inChatOf(item);
  // An item's done line is drawn only once it is done.
  const done = item.done!;
  const job = item.job;
  const ended = job !== null && jobForm(job.work) === 'ended';
  const note = item.wait?.note ?? null;
  return (
    <div className="line" onClick={onTap} data-testid="timeline.line">
      <LineLead item={item} />
      {item.form === 'wait' ? (
        <span className="title" title={title} data-testid="timeline.line.title">
          <LinkedText text={title} />
        </span>
      ) : (
        <Behind item={item} className="title" title={title} testId="timeline.line.title">
          <LinkedText text={title} nested />
        </Behind>
      )}
      <span className="line-acts">
        {!phone && ended && <JobMark job={job} />}
        {!phone && item.form !== 'wait' && <Open item={item} />}
        {done.undo && <Undo item={item} />}
        {!phone && <DiscussButton quote={quoteOfItem(item)} testId="timeline.line.discuss" />}
      </span>
      <LineAttachments item={item} />
      {job !== null && !ended && <JobButton job={job} />}
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
      {note !== null && (
        <span className="said" data-testid="timeline.line.wait-note">
          <span className="said-text" title={note}>
            <LinkedText text={note} />
          </span>
        </span>
      )}
    </div>
  );
}

/**
 * The line of an item Pilot is working on (F13.7), as a done line is: a dashed circle in the time's
 * grey in its kind's place, the title, the file's name before the read, Open once its text is read,
 * Discuss, what Pilot does on it, and when it was placed. It takes no answer.
 */
function PilotsLine({ item, pilots }: { item: TimelineItem; pilots: PilotsWork }) {
  const title = titleOf(item);
  return (
    <div className="line" data-testid="timeline.line">
      <span className="kind-icon" title="Pilot is working on it" data-testid="timeline.line.kind">
        <CircleDashed className="icon" aria-hidden="true" />
      </span>
      <span className="title" title={title} data-testid="timeline.line.title">
        <LinkedText text={title} />
      </span>
      {item.body !== null && <Open item={item} />}
      <DiscussButton quote={quoteOfItem(item)} testId="timeline.line.discuss" />
      <span className="pilots-slot">
        <PilotsButton pilots={pilots} testId="timeline.line.pilots" />
      </span>
      <Time at={item.created_at} format="clock" testId="timeline.line.time" />
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
 * Open: what is behind the line (F13.3, F26.6).
 */
function Open({ item }: { item: TimelineItem }) {
  const work = item.kind === 'work';
  return (
    <Behind
      item={item}
      className="btn btn-ghost btn-sm btn-icon"
      title={work ? 'Open the session log' : 'Open the document'}
      label="Open"
      testId="timeline.line.open"
    >
      {work ? <ScrollText className="icon" aria-hidden="true" /> : <FileText className="icon" aria-hidden="true" />}
    </Behind>
  );
}

interface BehindProps {
  item: TimelineItem;
  className: string;
  title: string;
  label?: string;
  testId: string;
  children: ReactNode;
}

/**
 * A link to what is behind a done line: the item's document, as it was done, at the document's
 * address (F13.3); a work item's session log, at its session's (F26.6).
 */
function Behind({ item, className, title, label, testId, children }: BehindProps) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const replace = useTabReplace();
  const shared = { replace, className, title, 'aria-label': label, 'data-testid': testId };
  return item.kind === 'work' ? (
    <Link to="/projects/$projectId/sessions/$sessionId" params={{ projectId, sessionId: item.id }} {...shared}>
      {children}
    </Link>
  ) : (
    <Link to="/projects/$projectId/documents/$documentId" params={{ projectId, documentId: item.id }} {...shared}>
      {children}
    </Link>
  );
}

/** A tap on the line, on a phone: what its title opens, unless the tap is on a control of its own (F13.9). */
function useOpenLine(item: TimelineItem) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const navigate = useNavigate();
  return (event: MouseEvent) => {
    if (onControl(event)) return;
    if (item.kind === 'work') {
      void navigate({ to: '/projects/$projectId/sessions/$sessionId', params: { projectId, sessionId: item.id } });
    } else {
      void navigate({ to: '/projects/$projectId/documents/$documentId', params: { projectId, documentId: item.id } });
    }
  };
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

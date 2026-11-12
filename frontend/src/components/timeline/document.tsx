/**
 * A document item (F24): many blocks under one title, its head carrying *Edited <time>* (F28.7) and
 * *Unsent* while it has an answer and no Done (D026). One under about 150 words of its own (F24.1)
 * stands inline: its head; its title; its prose with every block answered in place, each in a panel
 * of its own, each section Pilot settled collapsed to its line (F31.5), and each block Pilot's work
 * holds its section's line (F31.7); its attachments (F17.5); Pilot's dots while it writes (F35);
 * then its segment bar beside *Send answers* (F33), the bar empty and *Send answers* enabled where it
 * has no block. A segment goes to its block, and a held block's is in the plan donut's in-progress
 * colour. *Send answers* is the document's Done (F24.3): it enables once every block is answered or
 * has a recommendation, and none is held, and clicked with unanswered recommended blocks it lists
 * them in a dialog whose Confirm sends, the record answering them with their recommendation (F32.5).
 *
 * A larger one, and every review (F25.1), leaves a card: its head, its title, its summary (F34),
 * its count chips (F24.2) and the auto pilot chip, counting the confirmations the switch would
 * answer (F4.4), its segment bar, or for a text with no block "N min read", its attachments, Open, and on a review
 * Reviewed (F25.2); Pilot's dots end it while Pilot writes. Open opens the overlay at the document's address, and a segment opens
 * it at its block's (F33, F97). A registered document has no text until its file is read at its
 * run's end, nor after a read that failed: awaiting its read, it is Pilot's line (item.tsx, F13.7);
 * its read failed, its card titles it by its file's name, a warning chip beside it, *Did not load*,
 * since only then does it wait on the person's Reviewed (F85.1, ruling D1); published, it is any
 * review's card. Where Pilot asked a registered document's writer about a block, the block's head
 * says so, inline and in the overlay (F52.2; writer-asked.tsx); a card says nothing of it.
 */

import { useContext, useState } from 'react';
import { Link, useNavigate } from '@tanstack/react-router';
import { Check, FileText } from 'lucide-react';
import { ConfirmDialog } from '@/components/shared/dialog';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Attachments } from '@/components/timeline/attachments';
import { AutopilotChip } from '@/components/timeline/autopilot-mark';
import { Block } from '@/components/timeline/block';
import { askOf, countsOf, isUnsent, readOf, recommendationOf, type Counts } from '@/components/timeline/document-state';
import { blockKey, GoToContext } from '@/components/timeline/flash';
import { Edited, ItemHead } from '@/components/timeline/item-head';
import { LockedContext } from '@/components/timeline/locked';
import { autopilotMayTake } from '@/components/timeline/may-take';
import { isSettled, piecesOf, SectionsContext, underHeading, type Fold } from '@/components/timeline/sections';
import { SettledHead, SettledLines } from '@/components/timeline/settled';
import { PilotWriting } from '@/components/timeline/writing';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import { useHandedFocus } from '@/hooks/use-handed-focus';
import { useReviewed, useSend } from '@/hooks/use-marks';
import { useShownProject } from '@/hooks/use-project-address';
import { useArchived, useAutopilotOff } from '@/hooks/use-projects';
import { blocksOf, isAnswered, titleOf, type Block as BlockData, type TimelineItem } from '@/hooks/use-timeline';
import { cn } from '@/lib/utils';

function DocumentHead({ item }: { item: TimelineItem }) {
  return (
    <ItemHead item={item}>
      {item.edited_at !== null && <Edited at={item.edited_at} />}
      {isUnsent(item) && <UnsentChip />}
    </ItemHead>
  );
}

export function InlineDocument({ item }: { item: TimelineItem }) {
  return (
    <div className="item-body">
      <DocumentHead item={item} />
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      <div className="inline-doc" data-testid="timeline.item.document">
        <DocumentParts item={item} />
      </div>
      <Attachments item={item} />
      {item.writing && <PilotWriting />}
      <div className="item-actions doc-actions">
        <SegmentBar item={item} />
        <span className="grow" />
        <SendAnswers item={item} />
      </div>
    </div>
  );
}

export function DocumentCard({ item }: { item: TimelineItem }) {
  const { id: projectId, address } = useShownProject();
  const navigate = useNavigate();
  const replace = useTabReplace();
  const blocks = blocksOf(item);
  const autopilotOff = useAutopilotOff(projectId);
  const read = readOf(item);
  const params = { address, documentId: item.id };
  const openAt = (itemId: string, blockId: string) =>
    void navigate({ to: '/projects/$address/items/$itemId/blocks/$blockId', params: { address, itemId, blockId }, replace });
  return (
    <div className="item-body">
      <DocumentHead item={item} />
      <div className={cn('doc-card', read)} data-testid="timeline.item.card" data-read={read ?? undefined}>
        <div className="title-row">
          <div className="item-title" data-testid="timeline.item.title">
            <LinkedText text={titleOf(item)} />
          </div>
          {read === 'failed' && <DidNotLoadChip />}
        </div>
        {item.summary !== null && (
          <p className="item-sub" data-testid="timeline.item.summary">
            <LinkedText text={item.summary} />
          </p>
        )}
        <CountChips counts={countsOf(item)} autopilot={blocks.filter((block) => autopilotMayTake(item, block, autopilotOff)).length} />
        {item.body !== null && (
          <div className="progress">
            {blocks.length > 0 ? (
              <GoToContext.Provider value={openAt}>
                <SegmentBar item={item} />
              </GoToContext.Provider>
            ) : (
              // The API counts the words of every item it gives a text.
              <span data-testid="timeline.item.read-time">{item.read_minutes!} min read</span>
            )}
          </div>
        )}
        <Attachments item={item} />
        <div className="item-actions">
          <Link
            to="/projects/$address/documents/$documentId"
            params={params}
            replace={replace}
            className="btn btn-primary"
            data-testid="timeline.item.open"
          >
            <FileText className="icon" aria-hidden="true" />
            Open
          </Link>
          {item.kind === 'review' && <Reviewed item={item} />}
        </div>
      </div>
      {item.writing && <PilotWriting />}
    </div>
  );
}

const COUNTED: [keyof Counts, (count: number) => string][] = [
  ['decision', (count) => `${count} ${count === 1 ? 'decision' : 'decisions'}`],
  ['question', (count) => `${count} ${count === 1 ? 'question' : 'questions'}`],
  ['action', (count) => `${count} ${count === 1 ? 'action' : 'actions'}`],
  ['settled', (count) => `${count} settled by Pilot`],
  ['deferred', (count) => `${count} deferred`],
];

/** A chip for each count but none, then the auto pilot chip unless it counts none. */
function CountChips({ counts, autopilot }: { counts: Counts; autopilot: number }) {
  const shown = COUNTED.filter(([key]) => counts[key] > 0);
  if (shown.length === 0 && autopilot === 0) return null;
  return (
    <div className="counts" data-testid="timeline.item.counts">
      {shown.map(([key, words]) => (
        <span key={key} className="chip" data-testid="timeline.item.count" data-count={key}>
          {words(counts[key])}
        </span>
      ))}
      {autopilot > 0 && <AutopilotChip count={autopilot} />}
    </div>
  );
}

/** A review's one mark: read, nothing to answer (F25.2); disabled while the project is archived (D012). */
function Reviewed({ item }: { item: TimelineItem }) {
  const { id: projectId } = useShownProject();
  const { mark, pending } = useReviewed(item.id);
  const archived = useArchived(projectId);
  return (
    <button type="button" className="btn" onClick={mark} disabled={pending || archived} data-testid="timeline.item.reviewed">
      <Check className="icon" aria-hidden="true" />
      Reviewed
    </button>
  );
}

/** A registered document whose read failed: it waits on the person's Reviewed (F85.1, ruling D1). */
function DidNotLoadChip() {
  return (
    <span className="chip did-not-load" title="Its file could not be read at the end of its run" data-testid="timeline.item.did-not-load">
      Did not load
    </span>
  );
}

export function UnsentChip() {
  return (
    <span className="chip unsent" title="Answered, and not sent to Pilot yet" data-testid="timeline.item.unsent">
      Unsent
    </span>
  );
}

/**
 * A document's prose and its blocks in their order, every block answered in place, each section
 * Pilot settled, while not opened, its line in its block's place, consecutive lines one list, and
 * opened, under its head in its heading's place, the line or the head pressed handing the keyboard
 * focus to the one that replaces it; and each block Pilot's work holds its section's line, unless
 * the document is Pilot's (F28.9).
 */
export function DocumentParts({ item }: { item: TimelineItem }) {
  const { opened, open, close } = useContext(SectionsContext);
  const locked = useContext(LockedContext);
  const focus = useHandedFocus();
  const foldOf = (block: BlockData): Fold => {
    if (!locked && block.held !== null) return 'held';
    if (!isSettled(block)) return null;
    return opened.has(blockKey(item.id, block.id)) ? 'opened' : 'collapsed';
  };
  // The API gives every prose item but the opening its text.
  return piecesOf(item.body!, foldOf).map((piece) => {
    if (piece.type === 'settled') {
      return (
        <SettledLines
          key={`settled ${piece.blocks[0].id}`}
          blocks={piece.blocks}
          onOpen={(block) => {
            focus.hand(`head ${block.id}`);
            open(blockKey(item.id, block.id));
          }}
          button={(block) => focus.keep(`line ${block.id}`)}
        />
      );
    }
    if (piece.type === 'head') {
      return (
        <SettledHead
          key={`head ${piece.block.id}`}
          block={piece.block}
          onClose={() => {
            focus.hand(`line ${piece.block.id}`);
            close(blockKey(item.id, piece.block.id));
          }}
          button={focus.keep(`head ${piece.block.id}`)}
        />
      );
    }
    if (piece.type === 'held') {
      return <Block key={`block ${piece.block.id}`} item={item} block={piece.block} section={piece.section} />;
    }
    // The same keys whether its section is opened or no settled one, so that a person's answer in
    // an opened section redraws its block in place.
    const { part, index, headed } = piece;
    if (part.type === 'block') return <Block key={`block ${part.block.id}`} item={item} block={part.block} />;
    if (!headed) return <Markdown key={`prose ${index}`} text={part.markdown} />;
    const text = underHeading(part.markdown);
    return text.trim() === '' ? null : <Markdown key={`prose ${index}`} text={text} />;
  });
}

/** A segment per block, filled once the block is answered, half filled while Pilot's work holds it; each goes to its block. */
export function SegmentBar({ item }: { item: TimelineItem }) {
  const goTo = useContext(GoToContext);
  return (
    <div className="segbar" data-testid="timeline.segments">
      {blocksOf(item).map((block) => {
        const answered = isAnswered(block);
        const held = block.held !== null;
        const label = `${askOf(block)} · ${answered ? 'answered' : held ? 'Pilot is working on it' : 'open'}`;
        return (
          <button
            key={block.id}
            type="button"
            className={cn('seg', answered && 'done', held && 'held')}
            onClick={() => goTo(item.id, block.id)}
            title={label}
            aria-label={label}
            data-testid="timeline.segment"
            data-segment={block.id}
          />
        );
      })}
    </div>
  );
}

/** What a recommendation answers, as the dialog lists it. */
function recommendedWords(block: BlockData, answer: string): string {
  return block.proposal === null ? answer : `${answer}: ${block.proposal}`;
}

/** Why *Send answers* is disabled, or what it does. */
function sendTitle(held: boolean, ready: boolean): string {
  if (held) return 'Pilot is working on a block of it: send once Pilot is done';
  return ready ? 'Send the answers to Pilot' : 'Answer every block that has no recommendation first';
}

/** `onSent` runs once the record holds the answers; disabled while the project is archived (D012). */
export function SendAnswers({ item, onSent }: { item: TimelineItem; onSent?: () => void }) {
  const { id: projectId } = useShownProject();
  const { mark, pending } = useSend(item.id, onSent);
  const archived = useArchived(projectId);
  const [asking, setAsking] = useState(false);
  const blocks = blocksOf(item);
  const unanswered = blocks.filter((block) => !isAnswered(block));
  const held = blocks.some((block) => block.held !== null);
  const ready = !held && unanswered.every((block) => recommendationOf(block) !== null);
  const send = () => (unanswered.length > 0 ? setAsking(true) : mark());
  return (
    <>
      <button
        type="button"
        className="btn btn-primary"
        onClick={send}
        disabled={!ready || pending || archived}
        title={sendTitle(held, ready)}
        data-testid="timeline.item.send"
      >
        <Check className="icon" aria-hidden="true" />
        Send answers
      </button>
      {asking && (
        <ConfirmDialog
          title="Send with the recommendations?"
          lines={unanswered.map((block) => `${askOf(block)} · ${recommendedWords(block, recommendationOf(block)!)}`)}
          note="These are unanswered: sending takes each recommendation as your answer."
          act={{ label: 'Confirm', icon: Check }}
          pending={pending}
          onConfirm={mark}
          onCancel={() => setAsking(false)}
          testId="timeline.send-dialog"
        />
      )}
    </>
  );
}

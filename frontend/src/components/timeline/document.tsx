/**
 * A document item (F24): many blocks under one title, its head carrying *Edited <time>* (F28.7) and
 * *Unsent* while it has an answer and no Done (D026). One under about 150 words of its own (F24.1)
 * stands inline: its head; its title; its prose with every block answered in place, each in a panel
 * of its own, and each section Pilot settled collapsed to its line (F31.5); its attachments
 * (F17.5); Pilot's dots while it writes (F35); then its segment bar beside *Send answers* (F33), the bar
 * empty and *Send answers* enabled where it has no block. A segment goes to its block.
 * *Send answers* is the document's Done (F24.3): it enables once every block is answered or has a
 * recommendation, and clicked with unanswered recommended blocks it lists them in a dialog whose
 * Confirm sends, the record answering them with their recommendation (F32.5).
 *
 * A larger one, and every review (F25.1), leaves a card: its head, its title, its summary (F34),
 * its count chips (F24.2), its segment bar, or for a text with no block "N min read", its
 * attachments, Open, which reads Continue while the document reads *Unsent*, and on a review
 * Reviewed (F25.2); Pilot's dots end it while Pilot writes. Open opens the overlay at the document's address, and a segment opens
 * it at its block's (F33, F97). A registered document has no text until its file is read at its
 * run's end, nor after a read that failed: a review whose card titles it by its file's name, and
 * which takes no Reviewed until that read is made (F85.1, ruling D1). Where Pilot asked a registered
 * document's writer about its blocks, its line under the title, or on a card under the summary,
 * says so: "Pilot asked the writer about D2 and D4" (F86.8).
 */

import { useContext, useState } from 'react';
import { Link, useNavigate, useParams } from '@tanstack/react-router';
import { Check, FileText } from 'lucide-react';
import { ConfirmDialog } from '@/components/shared/dialog';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Attachments } from '@/components/timeline/attachments';
import { Block } from '@/components/timeline/block';
import { askOf, countsOf, isUnsent, recommendationOf, type Counts } from '@/components/timeline/document-state';
import { blockKey, GoToContext } from '@/components/timeline/flash';
import { Edited, ItemHead } from '@/components/timeline/item-head';
import { isSettled, piecesOf, SectionsContext } from '@/components/timeline/sections';
import { SettledLines } from '@/components/timeline/settled';
import { WriterAsked } from '@/components/timeline/writer-asked';
import { PilotWriting } from '@/components/timeline/writing';
import { useReviewed, useSend } from '@/hooks/use-marks';
import { useArchived } from '@/hooks/use-projects';
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
      <WriterAsked item={item} />
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
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const navigate = useNavigate();
  const blocks = blocksOf(item);
  const params = { projectId, documentId: item.id };
  const openAt = (itemId: string, blockId: string) =>
    void navigate({ to: '/projects/$projectId/items/$itemId/blocks/$blockId', params: { projectId, itemId, blockId } });
  return (
    <div className="item-body">
      <DocumentHead item={item} />
      <div className="doc-card" data-testid="timeline.item.card">
        <div className="item-title" data-testid="timeline.item.title">
          <LinkedText text={titleOf(item)} />
        </div>
        {item.summary !== null && (
          <p className="item-sub" data-testid="timeline.item.summary">
            <LinkedText text={item.summary} />
          </p>
        )}
        <WriterAsked item={item} />
        <CountChips counts={countsOf(item)} />
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
            to="/projects/$projectId/documents/$documentId"
            params={params}
            className="btn btn-primary"
            data-testid="timeline.item.open"
          >
            <FileText className="icon" aria-hidden="true" />
            {isUnsent(item) ? 'Continue' : 'Open'}
          </Link>
          {item.kind === 'review' && !item.awaiting_read && <Reviewed item={item} />}
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

/** A chip for each count but none. */
function CountChips({ counts }: { counts: Counts }) {
  const shown = COUNTED.filter(([key]) => counts[key] > 0);
  if (shown.length === 0) return null;
  return (
    <div className="counts" data-testid="timeline.item.counts">
      {shown.map(([key, words]) => (
        <span key={key} className="chip" data-testid="timeline.item.count" data-count={key}>
          {words(counts[key])}
        </span>
      ))}
    </div>
  );
}

/** A review's one mark: read, nothing to answer (F25.2); disabled while the project is archived (D012). */
function Reviewed({ item }: { item: TimelineItem }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const { mark, pending } = useReviewed(item.id);
  const archived = useArchived(projectId);
  return (
    <button type="button" className="btn" onClick={mark} disabled={pending || archived} data-testid="timeline.item.reviewed">
      <Check className="icon" aria-hidden="true" />
      Reviewed
    </button>
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
 * A document's prose and its blocks in their order, every block answered in place, and each
 * section Pilot settled, while not opened, its line in its block's place, consecutive lines one
 * list.
 */
export function DocumentParts({ item }: { item: TimelineItem }) {
  const { opened, open } = useContext(SectionsContext);
  const collapsed = (block: BlockData) => isSettled(block) && !opened.has(blockKey(item.id, block.id));
  // The API gives every prose item but the opening its text.
  return piecesOf(item.body!, collapsed).map((piece) => {
    if (piece.type === 'settled') {
      return (
        <SettledLines
          key={`settled ${piece.blocks[0].id}`}
          blocks={piece.blocks}
          onOpen={(block) => open(blockKey(item.id, block.id))}
        />
      );
    }
    const { part, index } = piece;
    return part.type === 'block' ? (
      <Block key={`block ${part.block.id}`} item={item} block={part.block} />
    ) : (
      <Markdown key={`prose ${index}`} text={part.markdown} />
    );
  });
}

/** A segment per block, filled once the block is answered; each goes to its block. */
export function SegmentBar({ item }: { item: TimelineItem }) {
  const goTo = useContext(GoToContext);
  return (
    <div className="segbar" data-testid="timeline.segments">
      {blocksOf(item).map((block) => {
        const answered = isAnswered(block);
        const label = `${askOf(block)} · ${answered ? 'answered' : 'open'}`;
        return (
          <button
            key={block.id}
            type="button"
            className={cn('seg', answered && 'done')}
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

/** `onSent` runs once the record holds the answers; disabled while the project is archived (D012). */
export function SendAnswers({ item, onSent }: { item: TimelineItem; onSent?: () => void }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const { mark, pending } = useSend(item.id, onSent);
  const archived = useArchived(projectId);
  const [asking, setAsking] = useState(false);
  const blocks = blocksOf(item);
  const unanswered = blocks.filter((block) => !isAnswered(block));
  const ready = unanswered.every((block) => recommendationOf(block) !== null);
  const send = () => (unanswered.length > 0 ? setAsking(true) : mark());
  return (
    <>
      <button
        type="button"
        className="btn btn-primary"
        onClick={send}
        disabled={!ready || pending || archived}
        title={ready ? 'Send the answers to Pilot' : 'Answer every block that has no recommendation first'}
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

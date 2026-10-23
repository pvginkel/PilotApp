/**
 * A document item (F24): many blocks under one title. One under about 150 words of its own (F24.1)
 * stands inline: its head, with *Edited <time>* (F28.7) and *Unsent* while it has an answer and no
 * Done (D026); its title; its prose with every block answered in place, each in a panel of its own;
 * Pilot's dots while it writes (F35); then its segment bar beside *Send answers* (F33). A segment
 * goes to its block. *Send answers* is the document's Done (F24.3): it enables once every block is
 * answered or has a recommendation, and clicked with unanswered recommended blocks it lists them in
 * a dialog whose Confirm sends, the record answering them with their recommendation (F32.5).
 */

import { useContext, useState } from 'react';
import { Check } from 'lucide-react';
import { ConfirmDialog } from '@/components/shared/dialog';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Block } from '@/components/timeline/block';
import { askOf, isUnsent, recommendationOf } from '@/components/timeline/document-state';
import { GoToContext } from '@/components/timeline/flash';
import { Edited, ItemHead } from '@/components/timeline/item-head';
import { PilotWriting } from '@/components/timeline/writing';
import { useSend } from '@/hooks/use-marks';
import { blocksOf, isAnswered, titleOf, type Block as BlockData, type TimelineItem } from '@/hooks/use-timeline';
import { cn } from '@/lib/utils';

export function InlineDocument({ item }: { item: TimelineItem }) {
  return (
    <div className="item-body">
      <ItemHead item={item}>
        {item.edited_at !== null && <Edited at={item.edited_at} />}
        {isUnsent(item) && <UnsentChip />}
      </ItemHead>
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      <div className="inline-doc" data-testid="timeline.item.document">
        <DocumentParts item={item} />
      </div>
      {item.writing && <PilotWriting />}
      {blocksOf(item).length > 0 && (
        <div className="item-actions doc-actions">
          <SegmentBar item={item} />
          <span className="grow" />
          <SendAnswers item={item} />
        </div>
      )}
    </div>
  );
}

export function UnsentChip() {
  return (
    <span className="chip unsent" title="Answered, and not sent to Pilot yet" data-testid="timeline.item.unsent">
      Unsent
    </span>
  );
}

/** A document's prose and its blocks in their order, every block answered in place. */
export function DocumentParts({ item }: { item: TimelineItem }) {
  // The API gives every prose item but the opening its text.
  return item.body!.map((part, index) =>
    part.type === 'block' ? (
      <Block key={`block ${part.block.id}`} item={item} block={part.block} />
    ) : (
      <Markdown key={`prose ${index}`} text={part.markdown} />
    ),
  );
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

/** `onSent` runs once the record holds the answers. */
export function SendAnswers({ item, onSent }: { item: TimelineItem; onSent?: () => void }) {
  const { mark, pending } = useSend(item.id, onSent);
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
        disabled={!ready || pending}
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

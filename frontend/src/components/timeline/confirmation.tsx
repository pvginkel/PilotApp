/**
 * A confirmation (F22): Pilot's ask for the go on one act. Its item is a compact yellow card: the
 * head with its reason line, whose tooltip says the ground (F22.1); the title and the proposal
 * beside a check, Yes, and a cross, No (F22.2); No opening a console for the reason, which may stay
 * empty and is the note (F22.3); the prose folded under Details, which Less folds again (F22.4).
 * The check and the cross, with No's console, are the block's controls inside a document too
 * (F22.7). The answer given, or being saved, stays coloured.
 */

import { useState, type ReactNode } from 'react';
import { Check, ChevronDown, ChevronUp, X } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Console } from '@/components/timeline/console';
import { ItemHead } from '@/components/timeline/item-head';
import { Note } from '@/components/timeline/note';
import { Deferral, DEFERRED } from '@/components/timeline/said';
import { useAnswer, type Answer } from '@/hooks/use-answer';
import { blocksOf, isProse, titleOf, type Block, type TimelineItem } from '@/hooks/use-timeline';
import { cn } from '@/lib/utils';

const YES = 'Yes';
const NO = 'No';

/** An open confirmation item's card. */
export function Confirmation({ item }: { item: TimelineItem }) {
  const [block] = blocksOf(item);
  const { answer, saving } = useAnswer(item.id, block.id);
  const [details, setDetails] = useState(false);
  // The API gives every prose item but the opening its text.
  const prose = item.body!.filter(isProse);
  const deferred = saving === null && block.answer === DEFERRED;
  return (
    <div className="item-body">
      <ItemHead item={item} because={block.because} />
      <ConfirmControls
        item={item}
        block={block}
        chosen={saving === null ? block.answer : saving.answer}
        live={saving === null}
        address
        onAnswer={answer}
      >
        <div className="item-title" data-testid="timeline.item.title">
          <LinkedText text={titleOf(item)} />
        </div>
        <Proposal block={block} />
        {deferred ? <Deferral block={block} /> : saving === null && block.note !== null && <Note text={block.note} />}
      </ConfirmControls>
      {prose.length > 0 && (
        <div className="confirm-foot">
          <button
            type="button"
            className="link details"
            onClick={() => setDetails(!details)}
            aria-expanded={details}
            data-testid="timeline.confirm.details"
          >
            {details ? <ChevronUp className="icon" aria-hidden="true" /> : <ChevronDown className="icon" aria-hidden="true" />}
            {details ? 'Less' : 'Details'}
          </button>
        </div>
      )}
      {details && (
        <div className="confirm-prose" data-testid="timeline.confirm.prose">
          {prose.map((part, index) => (
            <Markdown key={index} text={part.markdown} />
          ))}
        </div>
      )}
    </div>
  );
}

/** What Yes does: a confirmation always carries its proposal. */
export function Proposal({ block }: { block: Block }) {
  return (
    <div className="proposal" data-testid="timeline.confirm.proposal">
      <LinkedText text={block.proposal!} />
    </div>
  );
}

interface ConfirmControlsProps {
  item: TimelineItem;
  block: Block;
  /** The answer that shows chosen: the one being saved, else the block's own. */
  chosen: string | null;
  /** Whether it takes an answer now. */
  live: boolean;
  /** Its row carries the block's address: on the card, where no block panel does. */
  address?: boolean;
  onAnswer: Answer;
  /** What the row says beside the check and the cross. */
  children: ReactNode;
}

export function ConfirmControls({ item, block, chosen, live, address = false, onAnswer, children }: ConfirmControlsProps) {
  const [refusing, setRefusing] = useState(false);
  const yes = () => {
    setRefusing(false);
    onAnswer(YES);
  };
  return (
    <>
      <div className="confirm-row" data-testid="timeline.confirm" data-block-id={address ? block.id : undefined}>
        <div className="confirm-text">{children}</div>
        <div className="yes-no">
          <button
            type="button"
            className={cn('yn yes', chosen === YES && 'chosen')}
            onClick={yes}
            disabled={!live}
            title={`Yes: ${block.proposal}`}
            aria-label="Yes"
            data-testid="timeline.confirm.yes"
          >
            <Check className="icon" aria-hidden="true" />
          </button>
          <button
            type="button"
            className={cn('yn no', chosen === NO && 'chosen')}
            onClick={() => setRefusing(!refusing)}
            disabled={!live}
            title="No, and say why"
            aria-label="No"
            aria-expanded={refusing}
            data-testid="timeline.confirm.no"
          >
            <X className="icon" aria-hidden="true" />
          </button>
        </div>
      </div>
      {live && refusing && (
        <Console
          className="no"
          field={`${item.id}/${block.id}/no`}
          label="No: why not"
          placeholder="No: why not? (you may leave it empty)"
          send="Send No"
          blankSends
          testId="timeline.confirm.console"
          onSend={(reason, onSaved) => onAnswer(NO, { note: reason, onSaved })}
          onClose={() => setRefusing(false)}
        />
      )}
    </>
  );
}

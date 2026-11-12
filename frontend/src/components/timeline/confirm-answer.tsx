/**
 * A confirmation answered inline (F22.2), drawn as an action is: its proposal as the text, Yes and
 * No in an action's row of buttons, plain, Yes the primary, neither tinted, chosen or not; No
 * opening a console for the reason, which may stay empty and is the note, closing once it is saved
 * (F22.3). Answered, it reads Yes or No, the reason under it, as an action reads its option; closed,
 * that line alone, under its proposal where it is read only and cannot open; opened in a done item,
 * its proposal and its buttons stand with it and take nothing (F31.2). On its card the proposal is
 * the item's text, over the block (confirmation.tsx).
 */

import { useState } from 'react';
import { LinkedText } from '@/components/shared/linked-text';
import { Console } from '@/components/timeline/console';
import { DEFERRED, Said } from '@/components/timeline/said';
import type { Answer, Saving } from '@/hooks/use-answer';
import type { Block } from '@/hooks/use-timeline';

const YES = 'Yes';
const NO = 'No';

/** What Yes does: a confirmation always carries its proposal. */
export function Proposal({ block }: { block: Block }) {
  return (
    <div className="proposal" data-testid="timeline.confirm.proposal">
      <LinkedText text={block.proposal!} />
    </div>
  );
}

interface ConfirmAnswerProps {
  /** The block's key, which its No's reason keeps its unsent words under. */
  field: string;
  block: Block;
  /** Its proposal stands over its block, as its card's text. */
  bare: boolean;
  saving: Saving | null;
  closed: boolean;
  /** Closed, it opens again; one read only does not, and so keeps its proposal closed. */
  opens: boolean;
  /** Whether it takes an answer now. */
  live: boolean;
  /** Its item is done: opened, its buttons stand and take nothing (F31.2). */
  settled: boolean;
  /** An archived project's: the buttons stand and take nothing (D012). */
  disabled?: boolean;
  onAnswer: Answer;
}

export function ConfirmAnswer({ field, block, bare, saving, closed, opens, live, settled, disabled = false, onAnswer }: ConfirmAnswerProps) {
  const [refusing, setRefusing] = useState(false);
  const answer = saving === null ? block.answer : saving.answer;
  const off = disabled || !live;
  const yes = () => {
    setRefusing(false);
    onAnswer(YES);
  };
  return (
    <>
      {!bare && (!closed || !opens) && <Proposal block={block} />}
      {answer !== null && answer !== DEFERRED && <Said words={answer} note={saving === null ? block.note : saving.note} boxed={false} />}
      {(live || settled) && !closed && (
        <div className="item-actions yes-no">
          <button type="button" className="btn btn-primary" onClick={yes} disabled={off} title={`Yes: ${block.proposal}`} data-testid="timeline.confirm.yes">
            {YES}
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => setRefusing(!refusing)}
            disabled={off}
            title="No, and say why"
            aria-expanded={refusing}
            data-testid="timeline.confirm.no"
          >
            {NO}
          </button>
        </div>
      )}
      {live && !closed && refusing && (
        <Console
          className="no"
          field={`${field}/no`}
          label="No: why not"
          placeholder="No: why not? (you may leave it empty)"
          send="Send No"
          blankSends
          testId="timeline.confirm.console"
          onSend={(reason, onSaved) =>
            onAnswer(NO, {
              note: reason,
              onSaved: () => {
                onSaved();
                setRefusing(false);
              },
            })
          }
          onClose={() => setRefusing(false)}
        />
      )}
    </>
  );
}

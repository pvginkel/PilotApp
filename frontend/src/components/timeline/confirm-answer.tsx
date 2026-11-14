/**
 * A confirmation answered inline (F22.2), drawn as an action is: its proposal as the text, Yes and
 * No in an action's row of buttons, plain, Yes the primary, neither tinted, chosen or not; No
 * opening a console for the reason, which may stay empty and is the note, closing once it is saved
 * (F22.3). Answered, it reads Yes or No, the reason under it, as an action reads its option; closed,
 * that line alone, under its proposal where it is read only and cannot open; opened in a done item,
 * its proposal and its buttons stand with it and take nothing (F31.2). On its card the proposal is
 * the item's text, over the block (confirmation.tsx). In a one-ask item a press only chooses
 * (F32.3): Yes and No are both plain, the one chosen a soft button, as an action's chosen option
 * is; No is chosen while its console stands open, which has no Send of its own and whose cross
 * gives the choice back; and the block's Send, at the row's end, sends the Yes, or the No with its
 * reason. While the answer saves the buttons stand, disabled, and the spinner shows once it has
 * waited (F148): at the Send's icon, or at the start of the Yes or the No that was the answer.
 */

import { useState } from 'react';
import { BusyIcon } from '@/components/shared/busy-icon';
import { LinkedText } from '@/components/shared/linked-text';
import { Console, ConsoleBox } from '@/components/timeline/console';
import { DEFERRED, Said } from '@/components/timeline/said';
import { SendChoice } from '@/components/timeline/send-choice';
import type { Answer, Saving } from '@/hooks/use-answer';
import type { Choosing } from '@/hooks/use-choice';
import type { Block } from '@/hooks/use-timeline';
import { useUnsentText } from '@/hooks/use-unsent-text';
import { cn } from '@/lib/utils';

const YES = 'Yes';
const NO = 'No';

/** A No's field, as its console names it. */
const WHY = { label: 'No: why not', placeholder: 'No: why not? (you may leave it empty)' };

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
  /** A one-ask item's choice, which its presses move and its Send sends; none where a press answers. */
  choice: Choosing | null;
  /** Its Send starts Pilot's work (F59.3). */
  starts: boolean;
}

export function ConfirmAnswer({ field, block, bare, saving, closed, opens, live, settled, disabled = false, onAnswer, choice, starts }: ConfirmAnswerProps) {
  const [opened, setOpened] = useState(false);
  // A No's reason in a one-ask item, where no console of its own holds it.
  const why = useUnsentText(`${field}/no`);
  const refusing = choice === null ? opened : choice.typing;
  const answer = saving === null ? block.answer : saving.answer;
  const off = disabled || !live;
  // What a one-ask item's presses chose: No while its console stands open; the answer being saved once sent.
  const chose = choice === null ? null : saving !== null ? saving.answer : choice.typing ? NO : choice.answer === YES ? YES : null;
  // Where a press is the answer, the button pressed has the spinner while it saves.
  const pressed = choice === null && saving !== null ? saving.answer : null;
  const yes = () => {
    setOpened(false);
    onAnswer(YES);
  };
  const send = () => {
    if (off || chose === null) return;
    const sent = () => {
      why.change('');
      choice!.sent();
    };
    onAnswer(chose, chose === NO ? { note: why.text, onSaved: sent } : { onSaved: sent });
  };
  const toggleNo = () => {
    if (choice === null) setOpened(!opened);
    else if (choice.typing) choice.back();
    else choice.type();
  };
  return (
    <>
      {!bare && (!closed || !opens) && <Proposal block={block} />}
      {answer !== null && answer !== DEFERRED && <Said words={answer} note={saving === null ? block.note : saving.note} boxed={false} />}
      {(live || settled || saving !== null) && !closed && (
        <div className="item-actions yes-no">
          <button
            type="button"
            className={cn('btn', choice === null ? 'btn-primary' : chose === YES && 'btn-soft')}
            onClick={choice === null ? yes : () => choice.choose(YES)}
            disabled={off}
            title={`Yes: ${block.proposal}`}
            data-testid="timeline.confirm.yes"
            data-chosen={chose === YES}
          >
            <BusyIcon busy={pressed === YES} />
            {YES}
          </button>
          <button
            type="button"
            className={cn('btn', chose === NO && 'btn-soft')}
            onClick={toggleNo}
            disabled={off}
            title="No, and say why"
            aria-expanded={refusing}
            data-testid="timeline.confirm.no"
            data-chosen={chose === NO}
          >
            <BusyIcon busy={pressed === NO} />
            {NO}
          </button>
          {choice !== null && <SendChoice ready={!off && chose !== null} busy={saving !== null} starts={starts} onSend={send} />}
        </div>
      )}
      {live &&
        !closed &&
        refusing &&
        (choice === null ? (
          <Console
            className="no"
            field={`${field}/no`}
            label={WHY.label}
            placeholder={WHY.placeholder}
            send="Send No"
            blankSends
            testId="timeline.confirm.console"
            onSend={(reason, onSaved) =>
              onAnswer(NO, {
                note: reason,
                onSaved: () => {
                  onSaved();
                  setOpened(false);
                },
              })
            }
            onClose={() => setOpened(false)}
          />
        ) : (
          <ConsoleBox
            className="no"
            text={why.text}
            onChange={why.change}
            label={WHY.label}
            placeholder={WHY.placeholder}
            send={null}
            autoFocus={choice.opened}
            testId="timeline.confirm.console"
            onSend={send}
            onClose={choice.back}
          />
        ))}
    </>
  );
}

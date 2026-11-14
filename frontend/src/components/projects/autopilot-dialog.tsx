/**
 * The switch's question as auto pilot turns on while confirmations it would have taken are open
 * (F4.2; ui-conventions, "Answering: notes and confirmations"). Yes turns it on answering them, the
 * person's Yes through auto pilot, and Pilot goes ahead; No, a click beside it or Esc turns it on
 * and leaves them open. No takes the focus as it opens, so that Enter pressed again leaves them.
 * The answer on its way has the spinner once it has waited (F148): at Yes's icon, at No's start.
 */

import { useRef } from 'react';
import { Check } from 'lucide-react';
import { BusyIcon } from '@/components/shared/busy-icon';
import { Dialog } from '@/components/shared/dialog';

const TEST_ID = 'project.autopilot-dialog';

interface AutopilotDialogProps {
  /** The open confirmations the switch would answer: the head's `autopilot_may_take`. */
  count: number;
  /** The answer on its way, whether it answers the confirmations: nothing closes the dialog but its answer; null while none is. */
  answering: boolean | null;
  /** Turns auto pilot on, answering the confirmations or not. */
  onAnswer: (answerConfirmations: boolean) => void;
}

export function AutopilotDialog({ count, answering, onAnswer }: AutopilotDialogProps) {
  const noButton = useRef<HTMLButtonElement>(null);
  const pending = answering !== null;
  const answer = (answerConfirmations: boolean) => {
    if (!pending) onAnswer(answerConfirmations);
  };
  const lines = [
    count === 1
      ? 'One open confirmation asks only because auto pilot is off.'
      : `${count} open confirmations ask only because auto pilot is off.`,
    `Yes answers ${count === 1 ? 'it' : 'them'} Yes for you, and Pilot goes ahead.`,
    `No leaves ${count === 1 ? 'it' : 'them'} open for you to answer.`,
  ];
  return (
    <Dialog
      title="Answer what auto pilot would take?"
      onClose={() => answer(false)}
      initialFocus={noButton}
      className="confirm"
      testId={TEST_ID}
    >
      <ul className="dialog-list">
        {lines.map((line) => (
          <li key={line} data-testid={`${TEST_ID}.line`}>
            {line}
          </li>
        ))}
      </ul>
      <p className="dialog-note" data-testid={`${TEST_ID}.note`}>
        Auto pilot turns on either way.
      </p>
      <div className="dialog-actions">
        <button ref={noButton} type="button" className="btn" disabled={pending} onClick={() => answer(false)} data-testid={`${TEST_ID}.no`}>
          <BusyIcon busy={answering === false} />
          No
        </button>
        <button type="button" className="btn btn-primary" disabled={pending} onClick={() => answer(true)} data-testid={`${TEST_ID}.yes`}>
          <BusyIcon busy={answering === true}>
            <Check className="icon" aria-hidden="true" />
          </BusyIcon>
          Yes
        </button>
      </div>
    </Dialog>
  );
}

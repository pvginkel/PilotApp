/**
 * A question answered inline (F20): the growing field, "Your answer" or "Default: …" from its
 * `default`, and Send (F20.1); Send with the field empty gives the default. Answered, the answer is
 * boxed (F20.2): from the click on, and where Pilot gave it, until opened to the field again.
 */

import { TextField } from '@/components/shared/text-field';
import { DEFERRED, Said } from '@/components/timeline/said';
import type { Answer, Saving } from '@/hooks/use-answer';
import type { Block } from '@/hooks/use-timeline';
import { useUnsentText } from '@/hooks/use-unsent-text';

interface QuestionAnswerProps {
  /** The block's key, which its fields keep their unsent words under. */
  field: string;
  block: Block;
  saving: Saving | null;
  closed: boolean;
  /** Whether it takes an answer now. */
  live: boolean;
  /** An archived project's: the controls stand and take nothing (D012). */
  disabled?: boolean;
  onAnswer: Answer;
}

export function QuestionAnswer({ field, block, saving, closed, live, disabled = false, onAnswer }: QuestionAnswerProps) {
  const own = block.answer === DEFERRED ? null : block.answer;
  if (closed || !live) {
    // An answer being saved is the person's, never Done.
    const words = saving === null ? own : saving.answer!;
    return words === null ? null : <Said words={words} note={saving === null ? block.note : saving.note} boxed />;
  }
  return <QuestionField field={field} block={block} initial={own ?? ''} disabled={disabled} onAnswer={onAnswer} />;
}

interface QuestionFieldProps {
  field: string;
  block: Block;
  /** What the field opens with while nothing is kept: the answer it changes. */
  initial: string;
  disabled: boolean;
  onAnswer: Answer;
}

function QuestionField({ field, block, initial, disabled, onAnswer }: QuestionFieldProps) {
  const { text, change, sent } = useUnsentText(`${field}/answer`, initial);
  const words = text.trim() === '' ? block.default : text;
  const send = () => {
    if (words !== null) onAnswer(words, { onSaved: sent });
  };
  return (
    <div className="field-row">
      <TextField
        value={text}
        onChange={change}
        onSend={send}
        label="Your answer"
        placeholder={block.default === null ? 'Your answer' : `Default: ${block.default}`}
        disabled={disabled}
        testId="timeline.block.field"
      />
      <button
        type="button"
        className="btn btn-primary"
        onClick={send}
        disabled={disabled || words === null}
        title="Send (Ctrl+Enter)"
        data-testid="timeline.block.send"
      >
        Send
      </button>
    </div>
  );
}

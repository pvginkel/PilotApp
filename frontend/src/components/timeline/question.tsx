/**
 * A question answered inline (F20): the growing field, "Your answer" or "Default: …" from its
 * `default`, and Send (F20.1); Send with the field empty gives the default. Answered, the answer is
 * boxed (F20.2): from the click on, and where Pilot gave it, until opened to the field again.
 */

import { TextField } from '@/components/shared/text-field';
import { DEFERRED, Said } from '@/components/timeline/said';
import type { Answer, Saving } from '@/hooks/use-answer';
import type { Block, TimelineItem } from '@/hooks/use-timeline';
import { useUnsentText } from '@/hooks/use-unsent-text';

interface QuestionAnswerProps {
  item: TimelineItem;
  block: Block;
  saving: Saving | null;
  closed: boolean;
  /** Whether it takes an answer now. */
  live: boolean;
  onAnswer: Answer;
}

export function QuestionAnswer({ item, block, saving, closed, live, onAnswer }: QuestionAnswerProps) {
  const own = block.answer === DEFERRED ? null : block.answer;
  if (closed || !live) {
    // An answer being saved is the person's, never Done.
    const words = saving === null ? own : saving.answer!;
    return words === null ? null : <Said words={words} note={saving === null ? block.note : saving.note} boxed />;
  }
  return <QuestionField item={item} block={block} initial={own ?? ''} onAnswer={onAnswer} />;
}

interface QuestionFieldProps {
  item: TimelineItem;
  block: Block;
  /** What the field opens with while nothing is kept: the answer it changes. */
  initial: string;
  onAnswer: Answer;
}

function QuestionField({ item, block, initial, onAnswer }: QuestionFieldProps) {
  const { text, change, sent } = useUnsentText(`${item.id}/${block.id}/answer`, initial);
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
        testId="timeline.block.field"
      />
      <button
        type="button"
        className="btn btn-primary"
        onClick={send}
        disabled={words === null}
        title="Send (Ctrl+Enter)"
        data-testid="timeline.block.send"
      >
        Send
      </button>
    </div>
  );
}

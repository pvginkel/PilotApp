/**
 * A question answered inline (F20): the growing field, "Your answer" or "Default: …" from its
 * `default`, and Send (F20.1); Send with the field empty gives the default. Answered, the answer is
 * boxed (F20.2): from the click on, and where Pilot gave it, until opened to the field again. While
 * it saves it stands boxed in the field's place, beside the Send, disabled, its icon, Lucide's send,
 * the spinner once the write has waited (F148). In a one-ask item whose close starts Pilot's work,
 * the Send's icon is the job's mark under the mouse (F59.3). Its Send carries the note under the
 * field once Pilot's note taken in a one-ask item puts one there (F168.2; sent-note.tsx).
 */

import { Send } from 'lucide-react';
import { BusyIcon } from '@/components/shared/busy-icon';
import { TextField } from '@/components/shared/text-field';
import { DEFERRED, Said } from '@/components/timeline/said';
import { SentNote } from '@/components/timeline/sent-note';
import type { Answer, Saving } from '@/hooks/use-answer';
import type { Block } from '@/hooks/use-timeline';
import { useUnsentText } from '@/hooks/use-unsent-text';

interface QuestionAnswerProps {
  /** The block's key, which its fields keep their unsent words under. */
  field: string;
  block: Block;
  saving: Saving | null;
  /**
   * Its block reads closed until opened, as one Pilot answered: the reload closes it again, so its
   * field holds the reload on words of the person's, never on the answer it opened with.
   */
  closable: boolean;
  closed: boolean;
  /** Whether it takes an answer now. */
  live: boolean;
  /** An archived project's: the controls stand and take nothing (D012). */
  disabled?: boolean;
  onAnswer: Answer;
  /** Its Send closes its one-ask item and starts Pilot's work (F59.3). */
  starts: boolean;
}

export function QuestionAnswer({ field, block, saving, closable, closed, live, disabled = false, onAnswer, starts }: QuestionAnswerProps) {
  const own = block.answer === DEFERRED ? null : block.answer;
  if (saving !== null && !closed) {
    // An answer being saved is the person's, never Done: boxed in the field's place, beside its Send.
    return (
      <div className="field-row">
        <Said words={saving.answer!} note={saving.note} boxed />
        <SendButton busy disabled starts={starts} />
      </div>
    );
  }
  if (closed || !live) {
    const words = saving === null ? own : saving.answer!;
    return words === null ? null : <Said words={words} note={saving === null ? block.note : saving.note} boxed />;
  }
  return <QuestionField field={field} block={block} initial={own ?? ''} closable={closable} disabled={disabled} onAnswer={onAnswer} starts={starts} />;
}

interface QuestionFieldProps {
  field: string;
  block: Block;
  /** What the field opens with while nothing is kept: the answer it changes. */
  initial: string;
  closable: boolean;
  disabled: boolean;
  onAnswer: Answer;
  starts: boolean;
}

function QuestionField({ field, block, initial, closable, disabled, onAnswer, starts }: QuestionFieldProps) {
  const { text, change, sent } = useUnsentText(`${field}/answer`, initial);
  // The note its Send carries, which Pilot's note taken puts there in a one-ask item (F168.2).
  const note = useUnsentText(`${field}/note`);
  const words = text.trim() === '' ? block.default : text;
  const send = () => {
    if (words === null) return;
    onAnswer(words, {
      note: note.text,
      onSaved: () => {
        sent();
        note.sent();
      },
    });
  };
  return (
    <>
      <div className="field-row">
        <TextField
          value={text}
          onChange={change}
          onSend={send}
          label="Your answer"
          placeholder={block.default === null ? 'Your answer' : `Default: ${block.default}`}
          disabled={disabled}
          survivesReload={!closable || text === initial}
          testId="timeline.block.field"
        />
        <SendButton busy={false} disabled={disabled || words === null} starts={starts} onSend={send} />
      </div>
      <SentNote note={note} disabled={disabled} onSend={send} />
    </>
  );
}

interface SendButtonProps {
  busy: boolean;
  disabled: boolean;
  starts: boolean;
  onSend?: () => void;
}

/** The question's Send; while what it sent saves, disabled, its icon the spinner once it has waited (F148). */
function SendButton({ busy, disabled, starts, onSend }: SendButtonProps) {
  return (
    <button type="button" className="btn btn-primary" onClick={onSend} disabled={disabled} title="Send (Ctrl+Enter)" data-testid="timeline.block.send">
      <BusyIcon busy={busy} starts={starts}>
        <Send className="icon" aria-hidden="true" />
      </BusyIcon>
      Send
    </button>
  );
}

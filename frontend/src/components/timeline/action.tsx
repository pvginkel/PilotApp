/**
 * An action answered inline (F21): a paste-back field and Done (F21.1); or its options as buttons,
 * the first the primary, and Other, whose console sends the words as the answer (F21.2). What was
 * pasted back is the note under the Done, the option or the words. Answered, it reads Done or the
 * option, the words boxed, the note under it (F21.5).
 */

import { useState } from 'react';
import { Check } from 'lucide-react';
import { TextField } from '@/components/shared/text-field';
import { Console } from '@/components/timeline/console';
import { DEFERRED, Said } from '@/components/timeline/said';
import type { Answer, Saving, Sent } from '@/hooks/use-answer';
import type { Block, TimelineItem } from '@/hooks/use-timeline';
import { useUnsentText } from '@/hooks/use-unsent-text';
import { cn } from '@/lib/utils';

interface ActionAnswerProps {
  item: TimelineItem;
  block: Block;
  saving: Saving | null;
  closed: boolean;
  /** Whether it takes an answer now. */
  live: boolean;
  onAnswer: Answer;
  onDone: (sent: Sent) => void;
}

export function ActionAnswer({ item, block, saving, closed, live, onAnswer, onDone }: ActionAnswerProps) {
  const said = saidOf(block, saving);
  return (
    <>
      {said !== null && <Said {...said} />}
      {live && !closed && <ActionControls item={item} block={block} onAnswer={onAnswer} onDone={onDone} />}
    </>
  );
}

/** What the action reads as answered: the one being saved, else the block's own; Done where it has no answer. */
function saidOf(block: Block, saving: Saving | null) {
  const answer = saving === null ? block.answer : saving.answer;
  const note = saving === null ? block.note : saving.note;
  if (answer === DEFERRED || (saving === null && answer === null && block.done === null)) return null;
  const words = answer ?? 'Done';
  return { words, note, boxed: answer !== null && !block.options.some((option) => option.label === answer) };
}

interface ActionControlsProps {
  item: TimelineItem;
  block: Block;
  onAnswer: Answer;
  onDone: (sent: Sent) => void;
}

function ActionControls({ item, block, onAnswer, onDone }: ActionControlsProps) {
  const pasted = useUnsentText(`${item.id}/${block.id}/paste`);
  const [typing, setTyping] = useState(false);
  const optioned = block.options.length > 0;
  const done = () => onDone({ note: pasted.text, onSaved: pasted.sent });
  const pick = (answer: string, onSaved?: () => void) =>
    onAnswer(answer, {
      note: pasted.text,
      onSaved: () => {
        pasted.sent();
        onSaved?.();
      },
    });
  return (
    // The field's parent: kept in view while it grows, with the buttons that send it.
    <div className="paste-back">
      <TextField
        value={pasted.text}
        onChange={pasted.change}
        onSend={optioned ? undefined : done}
        label="What to paste back"
        placeholder="What to paste back, if anything"
        testId="timeline.block.paste"
      />
      <div className="item-actions">
        {optioned ? (
          <>
            {block.options.map((option, index) => (
              <button
                key={option.label}
                type="button"
                className={cn('btn', index === 0 && 'btn-primary')}
                onClick={() => pick(option.label)}
                title={option.text ?? undefined}
                data-testid="timeline.block.act"
              >
                {option.label}
              </button>
            ))}
            {typing ? (
              <Console
                field={`${item.id}/${block.id}/other`}
                label="Other, in your own words"
                placeholder="Other: in your own words"
                send="Send"
                testId="timeline.block.console"
                onSend={pick}
                onClose={() => setTyping(false)}
              />
            ) : (
              <button type="button" className="btn" onClick={() => setTyping(true)} data-testid="timeline.block.other">
                Other…
              </button>
            )}
          </>
        ) : (
          <button type="button" className="btn btn-primary" onClick={done} title="Done (Ctrl+Enter)" data-testid="timeline.block.done">
            <Check className="icon" aria-hidden="true" />
            Done
          </button>
        )}
      </div>
    </div>
  );
}

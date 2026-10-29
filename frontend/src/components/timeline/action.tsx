/**
 * An action answered inline (F21): a paste-back field and Done (F21.1); or its options as buttons,
 * the first the primary, and Other, whose console sends the words as the answer (F21.2). What was
 * pasted back is the note under the Done, the option or the words. Answered, it reads Done or the
 * option, the words boxed, the note under it (F21.5). Claimed by Pilot and not yet done, it reads
 * "Pilot does it", linking the work item that does it, the claim's note under it, over a person's
 * controls (F21.6).
 */

import { useState } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import { Check } from 'lucide-react';
import { Avatar } from '@/components/shared/avatar';
import { TextField } from '@/components/shared/text-field';
import { Console } from '@/components/timeline/console';
import { Note } from '@/components/timeline/note';
import { DEFERRED, Said } from '@/components/timeline/said';
import type { Answer, Saving, Sent } from '@/hooks/use-answer';
import type { Block } from '@/hooks/use-timeline';
import { useUnsentText } from '@/hooks/use-unsent-text';
import { cn } from '@/lib/utils';

interface ActionAnswerProps {
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
  onDone: (sent: Sent) => void;
}

export function ActionAnswer({ field, block, saving, closed, live, disabled = false, onAnswer, onDone }: ActionAnswerProps) {
  const said = saidOf(block, saving);
  return (
    <>
      {saving === null && block.claim !== null ? <Claimed block={block} work={block.claim.work} /> : said !== null && <Said {...said} />}
      {live && !closed && <ActionControls field={field} block={block} disabled={disabled} onAnswer={onAnswer} onDone={onDone} />}
    </>
  );
}

type ClaimedWork = NonNullable<Block['claim']>['work'];

/** Pilot's claim: "Pilot does it", the work item that does it, where one is named, its link (F21.6). */
function Claimed({ block, work }: { block: Block; work: ClaimedWork }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  return (
    <div className="answer" data-testid="timeline.block.claim">
      <div className="claimed">
        <Avatar who="pilot" size="xs" />
        <span>Pilot does it</span>
        {work !== null && (
          <>
            <span className="sep">·</span>
            <Link
              to="/projects/$projectId/items/$itemId"
              params={{ projectId, itemId: work.id }}
              className="claimed-work"
              title="Go to the work item that does it"
              data-testid="timeline.block.claim.work"
            >
              {work.title}
            </Link>
          </>
        )}
      </div>
      {block.note !== null && <Note text={block.note} />}
    </div>
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
  field: string;
  block: Block;
  disabled: boolean;
  onAnswer: Answer;
  onDone: (sent: Sent) => void;
}

function ActionControls({ field, block, disabled, onAnswer, onDone }: ActionControlsProps) {
  const pasted = useUnsentText(`${field}/paste`);
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
        disabled={disabled}
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
                disabled={disabled}
                title={option.text ?? undefined}
                data-testid="timeline.block.act"
              >
                {option.label}
              </button>
            ))}
            {typing ? (
              <Console
                field={`${field}/other`}
                label="Other, in your own words"
                placeholder="Other: in your own words"
                send="Send"
                testId="timeline.block.console"
                onSend={pick}
                onClose={() => setTyping(false)}
              />
            ) : (
              <button type="button" className="btn" onClick={() => setTyping(true)} disabled={disabled} data-testid="timeline.block.other">
                Other…
              </button>
            )}
          </>
        ) : (
          <button
            type="button"
            className="btn btn-primary"
            onClick={done}
            disabled={disabled}
            title="Done (Ctrl+Enter)"
            data-testid="timeline.block.done"
          >
            <Check className="icon" aria-hidden="true" />
            Done
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * An action answered inline (F21): a paste-back field and Done (F21.1); or its options as buttons,
 * the first the primary, and Other, whose console sends the words as the answer (F21.2). What was
 * pasted back is the note under the Done, the option or the words. Answered, it reads Done or the
 * option, the words boxed, the note under it (F21.5). Claimed by Pilot and not yet done, it reads
 * "Pilot does it", linking the work item that does it, the claim's note under it, over its controls
 * (F21.6), unless its held line says so (held.tsx) or Pilot's work handed it back, when it reads
 * nothing of the claim. In a one-ask item its options only choose (F32.3): every one a plain
 * button, the one chosen a soft one; Other is a choice too, its console with no Send of its own
 * and its cross giving the choice back; and the block's Send, at the row's end, sends the choice
 * with the paste-back. Its Done, on one without options, sends as before. While the answer saves
 * its controls stand, disabled, and the spinner shows once it has waited (F148): at the Send's or
 * the Done's icon, at the start of the option that was the answer, or at Other's Send.
 */

import { useState } from 'react';
import { Link } from '@tanstack/react-router';
import { Check } from 'lucide-react';
import { Avatar } from '@/components/shared/avatar';
import { BusyIcon } from '@/components/shared/busy-icon';
import { TextField } from '@/components/shared/text-field';
import { Console, ConsoleBox } from '@/components/timeline/console';
import { OTHER } from '@/components/timeline/decision';
import { Note } from '@/components/timeline/note';
import { DEFERRED, Said } from '@/components/timeline/said';
import { SendChoice } from '@/components/timeline/send-choice';
import type { Answer, Saving, Sent } from '@/hooks/use-answer';
import type { Choosing } from '@/hooks/use-choice';
import { useTabReplace } from '@/hooks/use-doc-tabs';
import { useShownProject } from '@/hooks/use-project-address';
import type { Block } from '@/hooks/use-timeline';
import { useUnsentText } from '@/hooks/use-unsent-text';
import { cn } from '@/lib/utils';

interface ActionAnswerProps {
  /** The block's key, which its fields keep their unsent words under. */
  field: string;
  block: Block;
  /** Whether a claim on it reads "Pilot does it". */
  claimed: boolean;
  saving: Saving | null;
  /**
   * Its block reads closed until opened, as one Pilot answered: the reload closes it again, so its
   * paste-back holds the reload on what is pasted in it.
   */
  closable: boolean;
  closed: boolean;
  /** Whether it takes an answer now. */
  live: boolean;
  /** Its item is done: opened, its controls stand and take nothing (F31.2). */
  settled: boolean;
  /** An archived project's: the controls stand and take nothing (D012). */
  disabled?: boolean;
  onAnswer: Answer;
  onDone: (sent: Sent) => void;
  /** A one-ask item's choice, which its options move and its Send sends; none where a press answers. */
  choice: Choosing | null;
  /** Its Send, or its Done, closes its one-ask item and starts Pilot's work (F59.3). */
  starts: boolean;
}

export function ActionAnswer({ field, block, claimed, saving, closable, closed, live, settled, disabled = false, onAnswer, onDone, choice, starts }: ActionAnswerProps) {
  const said = saidOf(block, saving);
  return (
    <>
      {saving === null && block.claim !== null
        ? claimed && <Claimed block={block} work={block.claim.work} />
        : said !== null && <Said {...said} />}
      {(live || settled || saving !== null) && !closed && (
        <ActionControls
          field={field}
          block={block}
          closable={closable}
          saving={saving}
          disabled={disabled || !live}
          onAnswer={onAnswer}
          onDone={onDone}
          choice={block.options.length > 0 ? choice : null}
          starts={starts}
        />
      )}
    </>
  );
}

type ClaimedWork = NonNullable<Block['claim']>['work'];

/** Pilot's claim: "Pilot does it", the work item that does it, where one is named, its link (F21.6). */
function Claimed({ block, work }: { block: Block; work: ClaimedWork }) {
  const { address } = useShownProject();
  const replace = useTabReplace();
  return (
    <div className="answer" data-testid="timeline.block.claim">
      <div className="claimed">
        <Avatar who="pilot" size="xs" />
        <span>Pilot does it</span>
        {work !== null && (
          <>
            <span className="sep">·</span>
            <Link
              to="/projects/$address/items/$itemId"
              params={{ address, itemId: work.id }}
              replace={replace}
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
  closable: boolean;
  saving: Saving | null;
  disabled: boolean;
  onAnswer: Answer;
  onDone: (sent: Sent) => void;
  choice: Choosing | null;
  starts: boolean;
}

function ActionControls({ field, block, closable, saving, disabled, onAnswer, onDone, choice, starts }: ActionControlsProps) {
  const pasted = useUnsentText(`${field}/paste`);
  // Other's words in a one-ask item, where no console of its own holds them.
  const other = useUnsentText(`${field}/other`);
  const [opened, setOpened] = useState(false);
  const typing = choice === null ? opened : choice.typing;
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
  // What a one-ask item's presses chose, while its field is closed; the answer being saved once sent.
  const picked = saving === null ? (choice?.answer ?? null) : saving.answer;
  const chose = choice === null || (saving === null && choice.typing) ? null : (block.options.find((option) => option.label === picked)?.label ?? null);
  // Where a press is the answer, what was pressed has the spinner while it saves: an option, Other's Send, or Done.
  const pressed = choice === null && saving !== null ? saving.answer : undefined;
  const wordsBusy = pressed !== undefined && pressed !== null && !block.options.some((option) => option.label === pressed);
  const ready = !disabled && (typing ? other.text.trim() !== '' : chose !== null);
  const send = () => {
    if (!ready) return;
    pick(typing ? other.text : chose!, () => {
      other.change('');
      choice!.sent();
    });
  };
  return (
    // The field's parent: kept in view while it grows, with the buttons that send it.
    <div className="paste-back">
      <TextField
        value={pasted.text}
        onChange={pasted.change}
        onSend={optioned ? (choice === null ? undefined : send) : done}
        label="What to paste back"
        placeholder="What to paste back, if anything"
        disabled={disabled}
        survivesReload={!closable}
        testId="timeline.block.paste"
      />
      <div className="item-actions">
        {optioned ? (
          <>
            {block.options.map((option, index) => (
              <button
                key={option.label}
                type="button"
                className={cn('btn', choice === null ? index === 0 && 'btn-primary' : chose === option.label && 'btn-soft')}
                onClick={() => {
                  if (choice !== null) return choice.choose(option.label);
                  // Its press answers, which Other's field, left open, would answer a second time.
                  setOpened(false);
                  pick(option.label);
                }}
                disabled={disabled}
                title={option.text ?? undefined}
                data-testid="timeline.block.act"
                data-chosen={chose === option.label}
              >
                <BusyIcon busy={pressed === option.label} />
                {option.label}
              </button>
            ))}
            {!typing ? (
              <button
                type="button"
                className="btn"
                onClick={choice === null ? () => setOpened(true) : choice.type}
                disabled={disabled}
                data-testid="timeline.block.other"
              >
                Other…
              </button>
            ) : choice === null ? (
              <Console
                field={`${field}/other`}
                label={OTHER.label}
                placeholder={OTHER.placeholder}
                send="Send"
                busy={wordsBusy}
                testId="timeline.block.console"
                onSend={(words, onSaved) =>
                  pick(words, () => {
                    onSaved();
                    setOpened(false);
                  })
                }
                onClose={() => setOpened(false)}
              />
            ) : (
              <ConsoleBox
                text={other.text}
                onChange={other.change}
                label={OTHER.label}
                placeholder={OTHER.placeholder}
                send={null}
                autoFocus={choice.opened}
                className="over-send"
                testId="timeline.block.console"
                onSend={send}
                onClose={choice.back}
              />
            )}
            {choice !== null && <SendChoice ready={ready} busy={saving !== null} starts={starts} onSend={send} />}
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
            <BusyIcon busy={saving !== null} starts={starts}>
              <Check className="icon" aria-hidden="true" />
            </BusyIcon>
            Done
          </button>
        )}
      </div>
    </div>
  );
}

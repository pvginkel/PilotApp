/**
 * A decision's options, answered inline (F19): full-width rows, each its label, its one line and
 * Recommended on the recommendation (F19.2); a proposal one row that agrees, tinted as the
 * recommendation (F19.3); and Other last, "Something else", which becomes a console: the growing
 * field with Send and a cross, Esc closing it as the cross does, and its words once saved (F17.2,
 * F19.4). An answer in free words is Other's row, chosen, with the words in it, and reopens the console with them; another
 * option chosen, the words stay there, unchosen. The chosen row fills; while the answer saves, and
 * once it no longer changes, the others fade and are disabled, Other among them, which goes only
 * from a done item's block that holds no words of it. Closed, the chosen row stands alone and
 * opens its block, or, read only, opens nothing. In a one-ask item a press only chooses (F32.3):
 * the row chosen fills as an answer's does and another press moves the choice; Other is a choice
 * too, its console with no Send of its own and its cross giving the choice back, its words kept in
 * its row, unchosen, under another choice; and the block's Send, in a row of its own under the
 * rows, disabled until a row is chosen or Other holds words, sends it, with the note over it once
 * Pilot's note taken puts one there (F168.2; sent-note.tsx). While an answer saves, the
 * spinner shows once it has waited (F148): a document's row being saved has it at its end, and a
 * one-ask item's Send at its icon.
 */

import { useState } from 'react';
import { BusyIcon } from '@/components/shared/busy-icon';
import { LinkedText } from '@/components/shared/linked-text';
import { Console, ConsoleBox } from '@/components/timeline/console';
import { Note } from '@/components/timeline/note';
import { SentNote } from '@/components/timeline/sent-note';
import { useTakenFocus } from '@/components/timeline/taken-focus';
import { SendChoice } from '@/components/timeline/send-choice';
import type { Answer } from '@/hooks/use-answer';
import type { Choosing } from '@/hooks/use-choice';
import type { Block } from '@/hooks/use-timeline';
import { useUnsentText } from '@/hooks/use-unsent-text';
import { cn } from '@/lib/utils';

/** A proposal's answer, and the label of a decision's one row where it proposes nothing. */
export const AGREE = 'Agree';

/** Other's field, as a decision's and an action's console name it. */
export const OTHER = { label: 'Other, in your own words', placeholder: 'Other: in your own words' };

/** What opening a closed block does, on its head's chevron and on a closed decision's row. */
export const EXPAND = 'Show expansion list';

interface Row {
  /** What choosing it answers. */
  answer: string;
  label: string;
  text: string | null;
  recommended: boolean;
}

function rowsOf(block: Block): Row[] {
  if (block.options.length > 0) {
    return block.options.map((option) => ({ answer: option.label, label: option.label, text: option.text, recommended: option.recommended }));
  }
  return [{ answer: AGREE, label: block.proposal ?? AGREE, text: null, recommended: true }];
}

interface DecisionOptionsProps {
  /** The block's key, which its fields keep their unsent words under. */
  field: string;
  block: Block;
  /** The answer that shows chosen: the one being saved, else the block's own. */
  chosen: string | null;
  /** The chosen answer is being saved. */
  saving: boolean;
  closed: boolean;
  /** Whether it takes an answer now. */
  live: boolean;
  /** Its item is done. */
  settled: boolean;
  /** An archived project's: the controls stand and take nothing (D012). */
  disabled?: boolean;
  /** Opens the closed block; none where it stays closed, its row taking nothing. */
  onOpen: (() => void) | null;
  onAnswer: Answer;
  /** A one-ask item's choice, which its presses move and its Send sends; none where a press answers. */
  choice: Choosing | null;
  /** Its Send starts Pilot's work (F59.3). */
  starts: boolean;
}

export function DecisionOptions({ field, block, chosen, saving, closed, live, settled, disabled = false, onOpen, onAnswer, choice, starts }: DecisionOptionsProps) {
  const [opened, setOpened] = useState(false);
  const rows = rowsOf(block);
  const single = block.options.length === 0;
  // Free words the block holds stay in Other's row, unchosen, while another option is chosen.
  const own = block.deferral === null ? block.answer : null;
  const held = own !== null && !rows.some((row) => row.answer === own) ? own : null;
  // Other's words in a one-ask item, where no console of its own holds them.
  const other = useUnsentText(`${field}/other`, held ?? '');
  const otherTaken = useTakenFocus(`${field}/other`);
  // The note a one-ask item's Send carries, which Pilot's note taken puts there (F168.2).
  const sentNote = useUnsentText(`${field}/note`);
  const typing = choice === null ? opened : choice.typing;
  // A one-ask item's choice shows chosen in the answer's place, from its first press until it is
  // sent, in the open block alone: closed, the block reads the answer the record holds.
  const made = choice !== null && live && !closed && (choice.typing || choice.answer !== null);
  const shown = made ? (typing ? null : choice.answer) : chosen;
  const picked = rows.findIndex((row) => row.answer === shown);
  const words = !made && chosen !== null && picked < 0 ? chosen : null;
  const typed = choice !== null && other.text.trim() !== '' ? other.text : null;
  const kept = words ?? typed ?? held;
  const ready = made && !disabled && (typing ? typed !== null : picked >= 0);
  const send = () => {
    if (!ready) return;
    const sent = () => {
      other.change('');
      sentNote.sent();
      choice!.sent();
    };
    onAnswer(typing ? other.text : rows[picked].answer, { note: sentNote.text, onSaved: sent });
  };
  // The block's note goes with the block's own answer, not with one being saved or chosen.
  const note = !made && chosen !== null && chosen === block.answer ? block.note : null;
  // A row's press is the answer where no Send is: the row being saved has the spinner at its end.
  const rowBusy = saving && choice === null;

  if (closed) {
    const row = rows[picked];
    return (
      <div className="options">
        <button
          type="button"
          className={cn('option chosen closed', single && 'single', row === undefined && 'other')}
          onClick={onOpen ?? undefined}
          disabled={onOpen === null}
          title={onOpen === null ? undefined : EXPAND}
          data-testid="timeline.block.option"
        >
          <RowWords label={row?.label ?? 'Other'} text={row === undefined ? words : row.text} />
          {note !== null && <Note text={note} nested />}
        </button>
      </div>
    );
  }

  return (
    <>
      <div className="options">
        {rows.map((row, index) => (
          <button
            key={row.answer}
            type="button"
            className={cn(
              'option',
              single && 'single',
              row.recommended && 'recommended',
              index === picked && 'chosen',
              !live && index !== picked && 'faded',
            )}
            onClick={() => (choice === null ? onAnswer(row.answer) : choice.choose(row.answer))}
            disabled={!live || disabled}
            data-testid="timeline.block.option"
            data-chosen={index === picked}
          >
            <RowWords label={row.label} text={row.text} />
            {row.recommended && !single && <span className="rec">Recommended</span>}
            <BusyIcon busy={rowBusy && index === picked} />
            {index === picked && note !== null && <Note text={note} nested />}
          </button>
        ))}
        {live && typing ? (
          choice === null ? (
            <Console
              field={`${field}/other`}
              initial={kept ?? ''}
              label={OTHER.label}
              placeholder={OTHER.placeholder}
              send="Send"
              testId="timeline.block.console"
              onSend={(words, onSaved) =>
                onAnswer(words, {
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
              text={other.text}
              onChange={other.change}
              label={OTHER.label}
              placeholder={OTHER.placeholder}
              send={null}
              autoFocus={choice.opened}
              fieldRef={otherTaken}
              className="over-send"
              testId="timeline.block.console"
              onSend={send}
              onClose={choice.back}
            />
          )
        ) : (
          (!settled || kept !== null) && (
            <button
              type="button"
              className={cn('option other', words !== null && 'chosen', !live && words === null && 'faded')}
              onClick={choice === null ? () => setOpened(true) : choice.type}
              disabled={!live || disabled}
              data-testid="timeline.block.other"
              data-chosen={words !== null}
            >
              <RowWords label="Other" text={kept ?? 'Something else'} />
              <BusyIcon busy={rowBusy && words !== null} />
              {words !== null && note !== null && <Note text={note} nested />}
            </button>
          )
        )}
      </div>
      {choice !== null && (
        <>
          <SentNote field={`${field}/note`} note={sentNote} disabled={!live || disabled} onSend={send} />
          <div className="item-actions">
            <SendChoice ready={ready} busy={saving} starts={starts} onSend={send} />
          </div>
        </>
      )}
    </>
  );
}

function RowWords({ label, text }: { label: string; text: string | null }) {
  return (
    <>
      <span className="label">
        <LinkedText text={label} nested />
      </span>
      {text !== null && (
        <span className="desc">
          <LinkedText text={text} nested />
        </span>
      )}
    </>
  );
}

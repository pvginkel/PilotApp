/**
 * A decision's options, answered inline (F19): full-width rows, each its label, its one line and
 * Recommended on the recommendation (F19.2); a proposal one row that agrees, tinted as the
 * recommendation (F19.3); and Other last, "Something else", which becomes a console: the growing
 * field with Send and a cross, Esc closing it as the cross does (F17.2, F19.4). An answer in free
 * words is Other's row, chosen, with the words in it, and reopens the console with them; another
 * option chosen, the words stay there, unchosen. The chosen row fills; once the answer no longer
 * changes, the others fade and are disabled. Closed, the chosen row stands alone and opens its
 * block.
 */

import { useState } from 'react';
import { Send, X } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { TextField } from '@/components/shared/text-field';
import { Note } from '@/components/timeline/note';
import { useUnsentText } from '@/hooks/use-unsent-text';
import type { Block, TimelineItem } from '@/hooks/use-timeline';
import { useEscape } from '@/lib/keys';
import { cn } from '@/lib/utils';

/** A proposal's answer, and the label of a decision's one row where it proposes nothing. */
const AGREE = 'Agree';

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
  item: TimelineItem;
  block: Block;
  /** The answer that shows chosen: the one being saved, else the block's own. */
  chosen: string | null;
  closed: boolean;
  /** Whether it takes an answer now. */
  live: boolean;
  onOpen: () => void;
  onAnswer: (answer: string, onSaved?: () => void) => void;
}

export function DecisionOptions({ item, block, chosen, closed, live, onOpen, onAnswer }: DecisionOptionsProps) {
  const [typing, setTyping] = useState(false);
  const rows = rowsOf(block);
  const single = block.options.length === 0;
  const picked = rows.findIndex((row) => row.answer === chosen);
  const words = chosen !== null && picked < 0 ? chosen : null;
  // Free words the block holds stay in Other's row, unchosen, while another option is chosen.
  const own = block.deferral === null ? block.answer : null;
  const kept = words ?? (own !== null && !rows.some((row) => row.answer === own) ? own : null);
  // The block's note goes with the block's own answer, not with one being saved.
  const note = chosen !== null && chosen === block.answer ? block.note : null;

  if (closed) {
    const row = rows[picked];
    return (
      <div className="options">
        <button
          type="button"
          className={cn('option chosen closed', single && 'single', row === undefined && 'other')}
          onClick={onOpen}
          title="Show every option"
          data-testid="timeline.block.option"
        >
          <RowWords label={row?.label ?? 'Other'} text={row === undefined ? words : row.text} />
          {note !== null && <Note text={note} nested />}
        </button>
      </div>
    );
  }

  return (
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
          onClick={() => onAnswer(row.answer)}
          disabled={!live}
          data-testid="timeline.block.option"
          data-chosen={index === picked}
        >
          <RowWords label={row.label} text={row.text} />
          {row.recommended && !single && <span className="rec">Recommended</span>}
          {index === picked && note !== null && <Note text={note} nested />}
        </button>
      ))}
      {live && typing ? (
        <OtherConsole
          field={`${item.id}/${block.id}/other`}
          initial={kept ?? ''}
          onSend={onAnswer}
          onClose={() => setTyping(false)}
        />
      ) : (
        (live || kept !== null) && (
          <button
            type="button"
            className={cn('option other', words !== null && 'chosen', !live && words === null && 'faded')}
            onClick={() => setTyping(true)}
            disabled={!live}
            data-testid="timeline.block.other"
            data-chosen={words !== null}
          >
            <RowWords label="Other" text={kept ?? 'Something else'} />
            {words !== null && note !== null && <Note text={note} nested />}
          </button>
        )
      )}
    </div>
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

interface OtherConsoleProps {
  /** Where its unsent words are kept in the browser. */
  field: string;
  /** The words it opens with while none are kept. */
  initial: string;
  onSend: (words: string, onSaved: () => void) => void;
  onClose: () => void;
}

/** Other's console, in Esc's order under everything else, and closed by Esc in its field too. */
function OtherConsole({ field, initial, onSend, onClose }: OtherConsoleProps) {
  const { text, change, sent } = useUnsentText(field, initial);
  useEscape('console', true, onClose);
  const blank = text.trim() === '';
  const send = () => {
    if (!blank) onSend(text, sent);
  };
  return (
    <div className="console" data-testid="timeline.block.console">
      <TextField
        value={text}
        onChange={change}
        onSend={send}
        onEscape={onClose}
        label="Other, in your own words"
        placeholder="Other: in your own words"
        autoFocus
        testId="timeline.block.console.field"
      />
      <button
        type="button"
        className="console-btn send"
        onClick={send}
        disabled={blank}
        title="Send (Ctrl+Enter)"
        aria-label="Send"
        data-testid="timeline.block.console.send"
      >
        <Send className="icon" aria-hidden="true" />
      </button>
      <button
        type="button"
        className="console-btn"
        onClick={onClose}
        title="Cancel (Esc)"
        aria-label="Cancel"
        data-testid="timeline.block.console.cancel"
      >
        <X className="icon" aria-hidden="true" />
      </button>
    </div>
  );
}

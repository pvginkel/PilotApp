/**
 * Pilot's note on a block (F168.1): what only Pilot knows about the ask, inside a block that is the
 * person's, between its head and its controls, at the top of an open one-ask panel, which draws no
 * head. A box on the page's colour under an amber triangle whose tooltip says the note is Pilot's,
 * and that it came after the ask came to the person where it did (F168.8); under it, each optional,
 * its few lines, the answer Pilot suggests and the note it suggests beside it. The writer's text,
 * its recommendation and the option's mark stay as written, and nothing of the note goes in the
 * block's head, on its segment or on the document's card. Once the block is answered the note is
 * one line (F168.3): the triangle, what Pilot suggested or the start of its text, and a chevron
 * that opens it whole, a long note shown whole; nothing puts a note away. Under what it suggests,
 * one button takes it, the answer and its note into the block as the person's own (F168.2;
 * take-note.ts).
 */

import { useState } from 'react';
import { ChevronDown, ChevronUp, StickyNote, TriangleAlert } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { HeadingWords, Markdown } from '@/components/shared/markdown';
import type { Take } from '@/components/timeline/take-note';
import type { Block } from '@/hooks/use-timeline';

export type PilotsNoteData = NonNullable<Block['pilots_note']>;

/** The note's triangle, its tooltip saying whose the note is and, for a late one, when it came. */
function NoteMark({ late }: { late: boolean }) {
  const title = late ? 'Pilot’s own note on this ask, not the writer’s, written since it came to you' : 'Pilot’s own note on this ask, not the writer’s';
  return (
    <span className="pn-mark" role="img" title={title} aria-label={title} data-testid="timeline.block.pilots-note.mark" data-late={late}>
      <TriangleAlert className="icon" aria-hidden="true" />
    </span>
  );
}

/** A text's first line with words on it. */
const firstLine = (text: string) => text.split('\n').find((line) => line.trim() !== '') ?? '';

interface PilotsNoteProps {
  note: PilotsNoteData;
  /** Its block is answered: the note stands as its line until opened. */
  answered: boolean;
  /** Its button, which puts what it suggests into the block (F168.2); none where there is nothing to take. */
  take: Take | null;
}

export function PilotsNote({ note, answered, take }: PilotsNoteProps) {
  const [opened, setOpened] = useState(false);
  if (answered && !opened) return <NoteLine note={note} onOpen={() => setOpened(true)} />;
  const suggests = note.suggested_answer !== null || note.suggested_note !== null;
  return (
    <div className="pilot-note" data-testid="timeline.block.pilots-note" data-line="false">
      <NoteMark late={note.late} />
      <div className="pn-body">
        {note.text !== null && (
          <div data-testid="timeline.block.pilots-note.text">
            <Markdown text={note.text} />
          </div>
        )}
        {suggests && (
          <div className="pn-suggest">
            <span className="pn-label">{note.suggested_answer === null ? 'Pilot would add' : 'Pilot would answer'}</span>
            {note.suggested_answer !== null && (
              <span className="pn-answer" data-testid="timeline.block.pilots-note.answer">
                {note.suggested_answer}
              </span>
            )}
            {note.suggested_note !== null && (
              <span className="note" data-testid="timeline.block.pilots-note.note">
                <StickyNote className="icon" aria-hidden="true" />
                <LinkedText text={note.suggested_note} />
              </span>
            )}
          </div>
        )}
        {take !== null && (
          <div className="pn-acts">
            <button type="button" className="btn btn-sm" onClick={take.take} title={take.title} data-testid="timeline.block.pilots-note.take">
              {take.label}
            </button>
          </div>
        )}
      </div>
      {answered && (
        <button
          type="button"
          className="btn btn-ghost btn-icon toggle"
          onClick={() => setOpened(false)}
          title="Fold the note to its line"
          aria-label="Fold the note to its line"
          aria-expanded="true"
          data-testid="timeline.block.pilots-note.toggle"
        >
          <ChevronUp className="icon" aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

/** An answered block's note as one line, which a click opens whole. */
function NoteLine({ note, onOpen }: { note: PilotsNoteData; onOpen: () => void }) {
  const lead = note.text ?? note.suggested_note;
  return (
    <div className="pilot-note one" onClick={onOpen} title="Open the note" data-testid="timeline.block.pilots-note" data-line="true">
      <NoteMark late={note.late} />
      <span className="one-text" data-testid="timeline.block.pilots-note.line">
        {note.suggested_answer !== null ? (
          <>
            Pilot would have answered <b>{note.suggested_answer}</b>
          </>
        ) : (
          lead !== null && <HeadingWords text={firstLine(lead)} />
        )}
      </span>
      {/* The line's own click opens it: the chevron's reaches it. */}
      <button
        type="button"
        className="btn btn-ghost btn-icon toggle"
        aria-label="Open the note"
        aria-expanded="false"
        data-testid="timeline.block.pilots-note.toggle"
      >
        <ChevronDown className="icon" aria-hidden="true" />
      </button>
    </div>
  );
}

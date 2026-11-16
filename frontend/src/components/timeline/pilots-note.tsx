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
 * take-note.ts). On an open action it may offer work Pilot would do on the person's word, the
 * action itself or something beside it, its button a primary one that starts Pilot's work
 * (F168.7, F59.3): pressed once, it places Pilot's job that starts the work item, and the note
 * folds to its line, which says so; the action stays the person's, with its Done. A note on the
 * document as a whole is the same box at the document's head, under its summary (F168.5).
 */

import { useState } from 'react';
import { ChevronDown, ChevronUp, Play, StickyNote, TriangleAlert } from 'lucide-react';
import { BusyIcon } from '@/components/shared/busy-icon';
import { LinkedText } from '@/components/shared/linked-text';
import { HeadingWords, Markdown } from '@/components/shared/markdown';
import type { Take } from '@/components/timeline/take-note';
import { useOffer } from '@/hooks/use-offer';
import type { Block } from '@/hooks/use-timeline';

export type PilotsNoteData = NonNullable<Block['pilots_note']>;

interface NoteMarkProps {
  late: boolean;
  /** What the note is on: an ask, or the document as a whole. */
  on: 'ask' | 'document';
  testId: string;
}

/** The note's triangle, its tooltip saying whose the note is and, for a late one, when it came. */
function NoteMark({ late, on, testId }: NoteMarkProps) {
  const own = `Pilot’s own note on this ${on}, not the writer’s`;
  const title = late ? `${own}, written since it came to you` : own;
  return (
    <span className="pn-mark" role="img" title={title} aria-label={title} data-testid={testId} data-late={late}>
      <TriangleAlert className="icon" aria-hidden="true" />
    </span>
  );
}

/** Where a note's offer is taken: its item's block. */
export interface OfferPlace {
  item: string;
  block: string;
}

/** A text's first line with words on it. */
const firstLine = (text: string) => text.split('\n').find((line) => line.trim() !== '') ?? '';

interface PilotsNoteProps {
  note: PilotsNoteData;
  /** Its block is answered: the note stands as its line until opened. */
  answered: boolean;
  /** Its button, which puts what it suggests into the block (F168.2); none where there is nothing to take. */
  take: Take | null;
  /** Where its offer's button takes it (F168.7); none where its offer cannot be taken now, or it has none. */
  offer: OfferPlace | null;
}

export function PilotsNote({ note, answered, take, offer }: PilotsNoteProps) {
  const [opened, setOpened] = useState(false);
  // Its block answered or its offer taken, it is its line.
  const folds = answered || note.offer_taken;
  if (folds && !opened) return <NoteLine note={note} onOpen={() => setOpened(true)} />;
  const suggests = note.suggested_answer !== null || note.suggested_note !== null;
  return (
    <div className="pilot-note" data-testid="timeline.block.pilots-note" data-line="false">
      <NoteMark late={note.late} on="ask" testId="timeline.block.pilots-note.mark" />
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
        {note.offer !== null && (
          <div className="pn-suggest">
            <span className="pn-label">{offerLabel(note)}</span>
            <span className="pn-answer" data-testid="timeline.block.pilots-note.offer">
              {note.offer}
            </span>
          </div>
        )}
        {(take !== null || offer !== null) && (
          <div className="pn-acts">
            {take !== null && (
              <button type="button" className="btn btn-sm" onClick={take.take} title={take.title} data-testid="timeline.block.pilots-note.take">
                {take.label}
              </button>
            )}
            {/* A replaced note's button is another's. */}
            {offer !== null && <StartWork key={note.id} place={offer} noteId={note.id} />}
          </div>
        )}
      </div>
      {folds && (
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

/** What the work a note offers is: started, once taken. */
const offerLabel = (note: PilotsNoteData) => (note.offer_taken ? 'Started as a work item' : 'Work Pilot would do');

/** The button that starts the work the note offers, once (F168.7): its icon the job's mark under the mouse (F59.3). */
function StartWork({ place, noteId }: { place: OfferPlace; noteId: number }) {
  const { take, pending } = useOffer(place.item, place.block, noteId);
  return (
    <button
      type="button"
      className="btn btn-primary btn-sm"
      onClick={take}
      disabled={pending}
      title="Pilot puts a work item for this on the timeline; the action stays yours, with its Done"
      data-testid="timeline.block.pilots-note.start"
    >
      <BusyIcon busy={pending} starts>
        <Play className="icon" aria-hidden="true" />
      </BusyIcon>
      Start a work item
    </button>
  );
}

/** What a note's line says: the work started, the answer Pilot suggested, the work it offers, or the start of its words. */
function LineWords({ note }: { note: PilotsNoteData }) {
  if (note.suggested_answer !== null && !note.offer_taken) {
    return (
      <>
        Pilot would have answered <b>{note.suggested_answer}</b>
      </>
    );
  }
  if (note.offer !== null) {
    return (
      <>
        {offerLabel(note)}: <b>{note.offer}</b>
      </>
    );
  }
  const lead = note.text ?? note.suggested_note;
  return lead === null ? null : <HeadingWords text={firstLine(lead)} />;
}

/** A note as one line, its block answered or its offer taken, which a click opens whole. */
function NoteLine({ note, onOpen }: { note: PilotsNoteData; onOpen: () => void }) {
  return (
    <div className="pilot-note one" onClick={onOpen} title="Open the note" data-testid="timeline.block.pilots-note" data-line="true">
      <NoteMark late={note.late} on="ask" testId="timeline.block.pilots-note.mark" />
      <span className="one-text" data-testid="timeline.block.pilots-note.line">
        <LineWords note={note} />
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

/** Pilot's note on a document as a whole (F168.5): the block's box, for what the document does not show. */
export function DocumentNote({ note }: { note: PilotsNoteData }) {
  return (
    <div className="pilot-note doc" data-testid="timeline.item.pilots-note">
      <NoteMark late={note.late} on="document" testId="timeline.item.pilots-note.mark" />
      <div className="pn-body" data-testid="timeline.item.pilots-note.text">
        {/* The API gives a note on an item as a whole its text alone. */}
        <Markdown text={note.text!} />
      </div>
    </div>
  );
}

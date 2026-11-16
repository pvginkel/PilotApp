/**
 * Taking Pilot's note (F168.2): one button puts the answer it suggests and its note into the block
 * as the person's own answer (F32.1), theirs to change until the Send. In a document a press on an
 * answer writes the record, so the take is that answer with its note, words no option has as free
 * words, a question's field opening on it once saved; one the block holds already, with that note,
 * takes none. A one-ask item writes nothing
 * before its Send (F32.3), so there the take is its choice, words no option has Other's words, a
 * question's field, with the note its Send carries: a decision's and a question's note field
 * (sent-note.tsx), an action's paste-back. A suggested note alone, on an open action, goes into
 * its paste-back, the Done still the person's. A note that offers work takes none: its offer's
 * button is its one (F168.7). The fields are the keys `<block key>/<part>` the
 * controls keep their unsent words under.
 */

import { AGREE } from '@/components/timeline/decision';
import type { PilotsNoteData } from '@/components/timeline/pilots-note';
import type { Answer } from '@/hooks/use-answer';
import type { Choosing } from '@/hooks/use-choice';
import { isAnswered, type Block } from '@/hooks/use-timeline';
import { putUnsentText } from '@/hooks/use-unsent-text';
import { keepUnsent } from '@/lib/browser-state';

export interface Take {
  label: string;
  title: string;
  take: () => void;
}

interface Taking {
  /** The block's key, which its fields keep their unsent words under. */
  field: string;
  block: Block;
  note: PilotsNoteData;
  /** The block's answer, where it takes one now. */
  answer: Answer;
  /** A one-ask item's choice, which its Send sends; none where a press answers. */
  choice: Choosing | null;
}

/** Whether `answer` is one a press on the block's own rows or buttons gives: an option, or a proposal's Agree. */
const pressed = (block: Block, answer: string) =>
  block.options.length > 0 ? block.options.some((option) => option.label === answer) : block.kind === 'decision' && answer === AGREE;

/** What taking the note does on the block; none where there is nothing to take, or where it offers work, whose own button stands there. */
export function takeOf({ field, block, note, answer, choice }: Taking): Take | null {
  if (note.offer !== null) return null;
  const suggested = note.suggested_answer;
  const words = note.suggested_note;
  const withNote = words === null ? '' : ', its note with it';
  if (suggested === null) {
    if (words === null || block.kind !== 'action' || isAnswered(block)) return null;
    return {
      label: 'Take this note',
      title: 'Put Pilot’s note in the field you paste back in: yours to change, the Done still yours',
      take: () => putUnsentText(`${field}/paste`, words),
    };
  }
  if (choice === null) {
    if (block.answer === suggested && block.note === words) return null;
    return {
      label: 'Take this answer',
      title: `Answer as Pilot suggests${withNote}: yours to change until the document is sent`,
      take: () =>
        answer(suggested, {
          note: words ?? undefined,
          // A question's words kept in its field go once the record holds the answer, as its Send's do.
          onSaved: block.kind === 'question' ? () => keepUnsent(`${field}/answer`, '') : undefined,
        }),
    };
  }
  return {
    label: 'Take this answer',
    title: `Choose what Pilot suggests${withNote}: yours to change before you send it`,
    take: () => {
      if (block.kind === 'question') {
        putUnsentText(`${field}/answer`, suggested);
      } else if (pressed(block, suggested)) {
        choice.choose(suggested);
      } else {
        putUnsentText(`${field}/other`, suggested);
        choice.type();
      }
      if (words !== null) putUnsentText(block.kind === 'action' ? `${field}/paste` : `${field}/note`, words);
    },
  };
}

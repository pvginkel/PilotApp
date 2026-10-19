/**
 * The plan's open notes (F57.2), the brain's working state, read only and never counted: the
 * plan's own behind a button in the head's icon group while it has any (F2.7), a step's beside it
 * in the plan popover (F3.6).
 */

import { StickyNote } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { Popover } from '@/components/shared/popover';
import type { ProjectHead } from '@/hooks/use-projects';

type Note = ProjectHead['notes'][number];

/** Each note's summary, then its content. */
export function NoteList({ notes, testId }: { notes: Note[]; testId: string }) {
  return (
    <ul className="note-list" data-testid={testId}>
      {notes.map((note) => (
        <li key={note.id} data-testid={`${testId}.note`}>
          <strong className="note-summary" data-testid={`${testId}.note.summary`}>
            <LinkedText text={note.summary} />
          </strong>
          <p className="note-content" data-testid={`${testId}.note.content`}>
            <LinkedText text={note.content} />
          </p>
        </li>
      ))}
    </ul>
  );
}

export function NotesButton({ notes }: { notes: Note[] }) {
  if (notes.length === 0) return null;
  return (
    <Popover
      label="The plan's notes"
      anchorClassName="head-icon"
      className="notes-pop"
      testId="project.notes"
      trigger={({ open, toggle }) => (
        <button
          type="button"
          className="btn btn-ghost btn-sm btn-icon"
          title="The plan's notes"
          aria-label="The plan's notes"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={toggle}
          data-testid="project.notes.button"
        >
          <StickyNote className="icon" aria-hidden="true" />
        </button>
      )}
    >
      <h3>The plan&rsquo;s notes</h3>
      <NoteList notes={notes} testId="project.notes.list" />
    </Popover>
  );
}

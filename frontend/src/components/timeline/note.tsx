/** A note under its answer, led by a note's icon, not an avatar: it is no quote (F17.4). */

import { StickyNote } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';

/** `nested`: the note stands inside the button of its answer's row. */
export function Note({ text, nested = false }: { text: string; nested?: boolean }) {
  return (
    <span className="note" data-testid="timeline.block.note">
      <StickyNote className="icon" aria-hidden="true" />
      <LinkedText text={text} nested={nested} />
    </span>
  );
}

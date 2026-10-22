/**
 * An answer that is no option's row, as its block reads it: a question's or an action's answer,
 * boxed where it is the person's own words (F20.2, F21.5), and a deferral, "Deferred to <task>", or
 * to the project's end (F31.4); each with its note under it (F17.4).
 */

import { LinkedText } from '@/components/shared/linked-text';
import { Note } from '@/components/timeline/note';
import type { Block } from '@/hooks/use-timeline';
import { cn } from '@/lib/utils';

/** The answer that stands for a block sent to a task of the plan, or to the project's end. */
export const DEFERRED = 'deferred';

export function Said({ words, note, boxed }: { words: string; note: string | null; boxed: boolean }) {
  return (
    <div className="answer" data-testid="timeline.block.said">
      <div className={cn('said', boxed && 'boxed')}>
        <LinkedText text={words} />
      </div>
      {note !== null && <Note text={note} />}
    </div>
  );
}

export function Deferral({ block }: { block: Block }) {
  return (
    <div className="answer" data-testid="timeline.block.deferred">
      <div className="said">
        {/* The API gives a deferred block its deferral; a title of none is the project's end. */}
        Deferred to <em>{block.deferral!.title ?? "the project's end"}</em>
      </div>
      {block.note !== null && <Note text={block.note} />}
    </div>
  );
}

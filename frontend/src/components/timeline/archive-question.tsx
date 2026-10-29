/**
 * The archive question (F5.6, D061): after any finish, the server's one question under the end
 * divider, "Archive the project?". Archive does what the menu's Archive does (F128.1), the project
 * leaving the list for Archived; Keep closes it, the project staying finished. Both stand disabled
 * from the click until the screens read the answer back.
 */

import { Archive, Check } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { ItemHead } from '@/components/timeline/item-head';
import { useAnswer } from '@/hooks/use-answer';
import { blocksOf, titleOf, type TimelineItem } from '@/hooks/use-timeline';

/** Its two options, as the server writes them. */
const ARCHIVE = 'Archive';
const KEEP = 'Keep';

export function ArchiveQuestion({ item }: { item: TimelineItem }) {
  return (
    <div className="item-body">
      <ItemHead item={item} />
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      <ArchiveAnswers item={item} />
    </div>
  );
}

/** The open question's Archive and Keep, which answer its one block: on the timeline and in the overlay alike. */
export function ArchiveAnswers({ item }: { item: TimelineItem }) {
  const [block] = blocksOf(item);
  const { answer, saving } = useAnswer(item.id, block.id);
  return (
    <div className="item-actions">
      <button
        type="button"
        className="btn btn-primary"
        onClick={() => answer(ARCHIVE)}
        disabled={saving !== null}
        data-testid="timeline.archive-question.archive"
      >
        <Archive className="icon" aria-hidden="true" />
        {ARCHIVE}
      </button>
      <button
        type="button"
        className="btn btn-soft"
        onClick={() => answer(KEEP)}
        disabled={saving !== null}
        data-testid="timeline.archive-question.keep"
      >
        <Check className="icon" aria-hidden="true" />
        {KEEP}
      </button>
    </div>
  );
}

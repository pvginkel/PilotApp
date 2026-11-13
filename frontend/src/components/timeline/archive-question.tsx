/**
 * The archive question (F5.6, D061): after any finish, the server's one question under the end
 * divider, "Archive the project?". Archive does what the menu's Archive does (F128.1), the project
 * leaving the list for Archived; Keep closes it, the project staying finished. Each is chosen first
 * and then sent, as in every one-ask item (F32.3): both plain buttons, the one chosen a soft one,
 * and Send at the row's end, disabled until one is chosen. All three stand disabled from the Send
 * until the screens read the answer back.
 */

import { Archive, Check } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { blockKey } from '@/components/timeline/flash';
import { ItemHead } from '@/components/timeline/item-head';
import { SendChoice } from '@/components/timeline/send-choice';
import { useAnswer } from '@/hooks/use-answer';
import { useChoice } from '@/hooks/use-choice';
import { blocksOf, titleOf, type TimelineItem } from '@/hooks/use-timeline';
import { cn } from '@/lib/utils';

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

/** The open question's Archive and Keep, which choose its one block's answer, and its Send: on the timeline and in the overlay alike. */
export function ArchiveAnswers({ item }: { item: TimelineItem }) {
  const [block] = blocksOf(item);
  const { answer, saving } = useAnswer(item.id, block.id);
  const choice = useChoice(blockKey(item.id, block.id));
  const chosen = saving === null ? choice.answer : saving.answer;
  return (
    <div className="item-actions">
      <button
        type="button"
        className={cn('btn', chosen === ARCHIVE && 'btn-soft')}
        onClick={() => choice.choose(ARCHIVE)}
        disabled={saving !== null}
        data-testid="timeline.archive-question.archive"
        data-chosen={chosen === ARCHIVE}
      >
        <Archive className="icon" aria-hidden="true" />
        {ARCHIVE}
      </button>
      <button
        type="button"
        className={cn('btn', chosen === KEEP && 'btn-soft')}
        onClick={() => choice.choose(KEEP)}
        disabled={saving !== null}
        data-testid="timeline.archive-question.keep"
        data-chosen={chosen === KEEP}
      >
        <Check className="icon" aria-hidden="true" />
        {KEEP}
      </button>
      <SendChoice
        ready={saving === null && (chosen === ARCHIVE || chosen === KEEP)}
        onSend={() => answer(chosen!, { onSaved: choice.sent })}
        testId="timeline.archive-question.send"
      />
    </div>
  );
}

/**
 * What a document's screens read from its item: whether it stands inline (F24.1), whether it reads
 * *Unsent* (D026), what a block asks and the answer Done records for it unanswered (F32.5).
 */

import { blockKindOf } from '@/components/timeline/kinds';
import { DEFERRED } from '@/components/timeline/said';
import { blocksOf, type Block, type TimelineItem } from '@/hooks/use-timeline';

/** Up to this many words of its own, a document stands inline; past it, it leaves a card. */
const INLINE_WORDS = 150;

/** Whether a document stands inline, by its own count, which no answer moves. */
export function isInline(item: TimelineItem): boolean {
  // The API counts the words of every item it gives a text.
  return item.word_count! <= INLINE_WORDS;
}

/**
 * Whether a document reads *Unsent* (D026): it has an answer, a person's or Pilot's, an action's
 * Done among them, and no Done. A deferral is no answer here, nor is a recommendation. `concept` is
 * a held save (F78), never this.
 */
export function isUnsent(item: TimelineItem): boolean {
  return (
    item.kind === 'document' &&
    item.done === null &&
    blocksOf(item).some((block) => block.done !== null || (block.answer !== null && block.answer !== DEFERRED))
  );
}

/**
 * The answer Done records for a block left unanswered, by the record's rule: a question's
 * default; Yes to a confirmation and Agree to another proposal; a decision's recommended option. An
 * action has none.
 */
export function recommendationOf(block: Block): string | null {
  switch (block.kind) {
    case 'action':
      return null;
    case 'question':
      return block.default;
    case 'decision':
      if (block.confirmation) return 'Yes';
      if (block.proposal !== null) return 'Agree';
      return block.options.find((option) => option.recommended)?.label ?? null;
    default: {
      const unknown: never = block.kind;
      throw new Error(`A block of kind ${String(unknown)} has no recommendation`);
    }
  }
}

/** What a block asks, as a segment and the dialog name it: its own section's heading, else its kind. */
export function askOf(block: Block): string {
  return block.section?.heading ?? blockKindOf(block).label;
}

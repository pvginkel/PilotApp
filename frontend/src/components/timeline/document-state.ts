/**
 * What a document's screens read from its item: whether it leaves a card (F24.1, F24.2, F25.1),
 * what its card counts (F24.2), whether it reads *Unsent* (D026), where a registered document's read
 * stands (F85.1), what a block asks and the answer Done records for it unanswered (F32.5).
 */

import { blockKindOf } from '@/components/timeline/kinds';
import { DEFERRED } from '@/components/timeline/said';
import { blocksOf, isAnswered, type Block, type TimelineItem } from '@/hooks/use-timeline';

/** Up to this many words of its own, a document stands inline; past it, it leaves a card. */
const INLINE_WORDS = 150;

/** Whether the item leaves a card: every review, and a document by its own count, which no answer moves. */
export function isCard(item: TimelineItem): boolean {
  // The API counts the words of every item it gives a text.
  return item.kind === 'review' || (item.kind === 'document' && item.word_count! > INLINE_WORDS);
}

/**
 * What a card counts: the blocks still the person's to answer or not, by kind, an action Pilot claimed
 * among them while it is open (F21.6), and what Pilot settled and deferred.
 */
export interface Counts {
  decision: number;
  question: number;
  action: number;
  settled: number;
  deferred: number;
}

export function countsOf(item: TimelineItem): Counts {
  const counts: Counts = { decision: 0, question: 0, action: 0, settled: 0, deferred: 0 };
  for (const block of blocksOf(item)) {
    if (block.answer === DEFERRED) counts.deferred += 1;
    else if (isAnswered(block) && block.by?.kind === 'agent') counts.settled += 1;
    else counts[block.kind] += 1;
  }
  return counts;
}

/**
 * Whether a document reads *Unsent* (D026): it has an answer, a person's or Pilot's, an action's
 * Done among them, and no Done. A deferral is no answer here, nor is a recommendation or a claim
 * not yet done. `concept` is a held save (F78), never this.
 */
export function isUnsent(item: TimelineItem): boolean {
  return item.kind === 'document' && item.done === null && blocksOf(item).some((block) => isAnswered(block) && block.answer !== DEFERRED);
}

/**
 * Where a registered document's read at its run's end stands while it has no text: `awaiting` it,
 * or `failed`, a document with no text whose read was made; null once its text is published, and on
 * every other item.
 */
export function readOf(item: TimelineItem): 'awaiting' | 'failed' | null {
  if (item.awaiting_read) return 'awaiting';
  return item.body === null && item.file_name !== null ? 'failed' : null;
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

/** What each Discuss quotes (F39.1, F38.3): an item, a block, a draft's block, a file of the project's folder by its path. */

import { blockKindOf } from '@/components/timeline/kinds';
import { blocksOf, titleOf, type Attachment, type Block, type TimelineItem } from '@/hooks/use-timeline';
import type { QuoteRef } from '@/lib/chat/quotes';

/**
 * A block as its quote names it: its own section's heading, else its kind, numbered among the
 * blocks of that kind in its document where it holds more than one, so that two decisions
 * under one heading, or under none, quote as "Decision 1 · Packing" and "Decision 2 · Packing".
 */
function nameOf(block: Block, blocks: readonly Block[]): string {
  if (block.section !== null) return block.section.heading;
  const { label } = blockKindOf(block);
  const alike = blocks.filter((each) => blockKindOf(each).label === label);
  return alike.length < 2 ? label : `${label} ${alike.findIndex((each) => each.id === block.id) + 1}`;
}

export const quoteOfItem = (item: TimelineItem): QuoteRef => ({ kind: 'item', id: item.id, label: titleOf(item) });

export const quoteOfBlock = (item: TimelineItem, block: Block): QuoteRef => ({
  kind: 'block',
  id: `${item.id}/${block.id}`,
  label: `${nameOf(block, blocksOf(item))} · ${titleOf(item)}`,
});

/** A draft's block by its path, `project.md/<local id>`, its label named among the draft's `blocks` and the draft's title. */
export const quoteOfDraftBlock = (block: Block, blocks: readonly Block[], title: string | null): QuoteRef => ({
  kind: 'block',
  id: `project.md/${block.id}`,
  label: `${nameOf(block, blocks)} · ${title ?? 'New project'}`,
});

/** A file of the project's folder by its path there: the handbook, the project document. */
export const quoteOfFile = (path: 'handbook.md' | 'project.md', title: string): QuoteRef => ({ kind: 'path', id: path, label: title });

export const quoteOfAttachment = (attachment: Attachment): QuoteRef => ({
  kind: 'path',
  id: `attachments/${attachment.batch}/${attachment.filename}`,
  label: attachment.title,
});

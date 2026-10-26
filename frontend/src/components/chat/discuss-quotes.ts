/** What each Discuss quotes (F39.1, F38.3): an item, a block, a file of the project's folder by its path. */

import { askOf } from '@/components/timeline/document-state';
import { titleOf, type Attachment, type Block, type TimelineItem } from '@/hooks/use-timeline';
import type { QuoteRef } from '@/lib/chat/quotes';

export const quoteOfItem = (item: TimelineItem): QuoteRef => ({ kind: 'item', id: item.id, label: titleOf(item) });

export const quoteOfBlock = (item: TimelineItem, block: Block): QuoteRef => ({
  kind: 'block',
  id: `${item.id}/${block.id}`,
  label: `${askOf(block)} · ${titleOf(item)}`,
});

/** A file of the project's folder by its path there: the handbook, the project document. */
export const quoteOfFile = (path: 'handbook.md' | 'project.md', title: string): QuoteRef => ({ kind: 'path', id: path, label: title });

export const quoteOfAttachment = (attachment: Attachment): QuoteRef => ({
  kind: 'path',
  id: `attachments/${attachment.batch}/${attachment.filename}`,
  label: attachment.title,
});

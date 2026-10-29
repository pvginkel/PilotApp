/**
 * Each kind's icon and label (F12.1): one icon for a decision and a question, one each for an
 * action, a notice, work, the card wait (a ticket) and the timed wait (the hourglass); a shield for
 * a confirmation, a book for a review, a speech bubble for the opening and the archive box for the
 * archive question (F5.6). A document carries its most common block's icon and "Document · N".
 */

import {
  Archive,
  BookOpen,
  FileText,
  Hand,
  Hourglass,
  Info,
  MessageCircleQuestion,
  MessageSquare,
  Shield,
  Terminal,
  Ticket,
  type LucideIcon,
} from 'lucide-react';
import { blocksOf, type Block, type TimelineItem } from '@/hooks/use-timeline';

interface Kind {
  label: string;
  icon: LucideIcon;
}

const KINDS: Record<TimelineItem['kind'], Kind> = {
  opening: { label: 'Opening', icon: MessageSquare },
  decision: { label: 'Decision', icon: MessageCircleQuestion },
  confirmation: { label: 'Confirm', icon: Shield },
  question: { label: 'Question', icon: MessageCircleQuestion },
  action: { label: 'Action', icon: Hand },
  notice: { label: 'Notice', icon: Info },
  document: { label: 'Document', icon: FileText },
  review: { label: 'Review', icon: BookOpen },
  archive_question: { label: 'Question', icon: Archive },
  work: { label: 'Work', icon: Terminal },
  card_wait: { label: 'Wait', icon: Ticket },
  timed_wait: { label: 'Wait', icon: Hourglass },
};

const BLOCK_KINDS: Record<Block['kind'], Kind> = {
  decision: KINDS.decision,
  question: KINDS.question,
  action: KINDS.action,
};

/** A block's icon and label, as its head shows them (F31.1): a confirmation's is its item's. */
export function blockKindOf(block: Block): Kind {
  return block.confirmation ? KINDS.confirmation : BLOCK_KINDS[block.kind];
}

export function kindOf(item: TimelineItem): Kind {
  if (item.kind !== 'document') return KINDS[item.kind];
  const blocks = blocksOf(item);
  // The first kind of the most frequent count, decisions before questions before actions.
  const counts = (['decision', 'question', 'action'] as const).map((kind) => ({
    kind,
    count: blocks.filter((block) => block.kind === kind).length,
  }));
  const top = counts.reduce((best, next) => (next.count > best.count ? next : best));
  return { label: `Document · ${blocks.length}`, icon: top.count > 0 ? BLOCK_KINDS[top.kind].icon : KINDS.document.icon };
}

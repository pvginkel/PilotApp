/**
 * A quote as a chip (F39.3), inside Pilot's text. Clicking it goes to the item or block.
 */

import { MessageSquareQuote, SquareCheckBig } from 'lucide-react';
import type { QuoteRef } from '@/lib/chat/quotes';
import { useChatActions } from './actions';

const QuoteIcon = ({ quote }: { quote: QuoteRef }) =>
  quote.kind === 'block' ? <SquareCheckBig className="icon-cap" aria-hidden /> : <MessageSquareQuote className="icon-cap" aria-hidden />;

/** Inside text: an inline chip in the primary's tint. */
export function QuoteChip({ quote, label }: { quote: QuoteRef; label: React.ReactNode }) {
  const { openQuote } = useChatActions();
  return (
    <button
      type="button"
      onClick={() => openQuote(quote)}
      title="Show it"
      className="mx-0.5 inline-flex max-w-full items-baseline gap-1 rounded-md bg-primary-muted px-1.5 align-baseline text-[0.92em] leading-[1.45] text-primary-muted-foreground hover:bg-primary-muted-strong"
    >
      <QuoteIcon quote={quote} />
      <span className="truncate">{label}</span>
    </button>
  );
}

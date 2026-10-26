/**
 * A quote (F39.3), as a line over a person's message it opens, or as a chip inside a text: its
 * icon — an item's, a block's, the handbook's, the project document's or an attachment's — and its
 * label. Clicking it goes to what it quotes.
 */

import { FileText, MessageSquareQuote, NotebookText, Paperclip, SquareCheckBig } from 'lucide-react';
import { useOpenQuote } from '@/hooks/use-open-quote';
import type { QuoteRef } from '@/lib/chat/quotes';

function QuoteIcon({ quote }: { quote: QuoteRef }) {
  const Icon =
    quote.kind === 'item'
      ? MessageSquareQuote
      : quote.kind === 'block'
        ? SquareCheckBig
        : quote.id === 'handbook.md'
          ? NotebookText
          : quote.id === 'project.md'
            ? FileText
            : Paperclip;
  return <Icon className="icon-cap" aria-hidden />;
}

/** Over a person's message: a quote it opens with, muted, one line. */
export function QuoteLine({ quote }: { quote: QuoteRef }) {
  const openQuote = useOpenQuote();
  return (
    <button
      type="button"
      onClick={() => openQuote(quote)}
      data-testid="chat.quote"
      data-quote={`${quote.kind} ${quote.id}`}
      title="Show it"
      className="mb-1 flex max-w-full items-baseline gap-1.5 text-left text-[12.5px] text-muted-foreground hover:[&>span]:underline"
    >
      <QuoteIcon quote={quote} />
      <span className="truncate">{quote.label}</span>
    </button>
  );
}

/** Inside text: an inline chip in the primary's tint. */
export function QuoteChip({ quote, label }: { quote: QuoteRef; label: React.ReactNode }) {
  const openQuote = useOpenQuote();
  return (
    <button
      type="button"
      onClick={() => openQuote(quote)}
      data-testid="chat.quote"
      data-quote={`${quote.kind} ${quote.id}`}
      title="Show it"
      className="mx-0.5 inline-flex max-w-full items-baseline gap-1 rounded-md bg-primary-muted px-1.5 align-baseline text-[0.92em] leading-[1.45] text-primary-muted-foreground hover:bg-primary-muted-strong"
    >
      <QuoteIcon quote={quote} />
      <span className="truncate">{label}</span>
    </button>
  );
}

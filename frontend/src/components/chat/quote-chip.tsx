/**
 * A quote (F39.3), as a line over a person's message it opens, as a chip inside a text, or over the
 * composer's field with its remove: its icon — an item's, a block's, the handbook's, the project
 * document's or an attachment's — and its label. Clicking the line or the chip goes to what it
 * quotes.
 */

import { FileText, MessageSquareQuote, NotebookText, Paperclip, SquareCheckBig, X } from 'lucide-react';
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

/** Over the composer's field: the quote Discuss put there, and its remove. */
export function ComposerQuote({ quote, onRemove }: { quote: QuoteRef; onRemove: () => void }) {
  return (
    <div
      className="mb-2 flex items-baseline gap-1.5 rounded-sm border-l-[3px] border-primary bg-primary-muted/60 py-0.5 pr-0.5 pl-2.5 text-[13px] text-primary-muted-foreground"
      data-testid="chat.composer.quote"
      data-quote={`${quote.kind} ${quote.id}`}
    >
      <QuoteIcon quote={quote} />
      <span className="min-w-0 flex-1 truncate" title={quote.label} data-testid="chat.composer.quote.label">
        {quote.label}
      </span>
      <button
        type="button"
        onClick={onRemove}
        title="Leave it out"
        aria-label="Leave the quote out"
        className="grid size-6 flex-none place-items-center self-center rounded-md hover:bg-primary-muted-strong"
        data-testid="chat.composer.quote.remove"
      >
        <X className="size-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}

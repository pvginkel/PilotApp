/**
 * Discuss (F39.1): quotes what it stands on into the project's chat, the side panel opening on the
 * Chat tab, on top, the quote in the composer (use-discuss.ts).
 */

import { MessagesSquare } from 'lucide-react';
import { useDiscuss } from '@/hooks/use-discuss';
import type { QuoteRef } from '@/lib/chat/quotes';
import { cn } from '@/lib/utils';

interface DiscussButtonProps {
  quote: QuoteRef;
  title?: string;
  className?: string;
  testId: string;
}

export function DiscussButton({ quote, title = 'Discuss: quote this into the project’s chat', className, testId }: DiscussButtonProps) {
  const discuss = useDiscuss();
  return (
    <button
      type="button"
      className={cn('btn btn-ghost btn-sm btn-icon', className)}
      onClick={() => discuss(quote)}
      title={title}
      aria-label="Discuss"
      data-testid={testId}
      data-quote={`${quote.kind} ${quote.id}`}
    >
      <MessagesSquare className="icon" aria-hidden="true" />
    </button>
  );
}

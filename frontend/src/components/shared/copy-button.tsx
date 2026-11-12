/**
 * A copy button: its text to the clipboard as it was written, a check in its icon's place for a
 * moment once copied, the mark the toast's copy shows (use-copy-to-clipboard.ts).
 */

import { Check, Copy } from 'lucide-react';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';
import { cn } from '@/lib/utils';

interface CopyButtonProps {
  text: string;
  /** What it copies, its tooltip and its name: "Copy the document’s text". */
  title: string;
  className?: string;
  testId: string;
}

export function CopyButton({ text, title, className, testId }: CopyButtonProps) {
  const { copyState, copy } = useCopyToClipboard();
  const Icon = copyState === 'success' ? Check : Copy;
  return (
    <button
      type="button"
      className={cn('btn btn-ghost btn-sm btn-icon', className)}
      onClick={() => copy(text)}
      title={title}
      aria-label={title}
      data-testid={testId}
      data-copy-state={copyState}
    >
      <Icon className="icon" aria-hidden="true" />
    </button>
  );
}

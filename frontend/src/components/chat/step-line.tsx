/**
 * One muted line of a reply's steps: an icon, the words, a chevron when it opens. A line whose
 * call runs shows a spinner in its icon's place once that call has run a second.
 */

import { useEffect, useState } from 'react';
import { ChevronRight, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

/** How long a call runs before its line shows a spinner. */
const SPINNER_AFTER_MS = 1000;

/** Whether `id`, a running call's, has stood for SPINNER_AFTER_MS; another call starts the wait over. */
function useSpinner(id: string | null): boolean {
  const [ran, setRan] = useState<string | null>(null);
  useEffect(() => {
    if (id === null) return;
    const timer = window.setTimeout(() => setRan(id), SPINNER_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [id]);
  return id !== null && ran === id;
}

export function StepLine({
  icon,
  running = null,
  tone = 'muted',
  open,
  onToggle,
  link,
  children,
  className,
}: {
  icon: React.ReactNode;
  /** The id of the call that runs, if one does. */
  running?: string | null;
  tone?: 'muted' | 'error' | 'success';
  open?: boolean;
  onToggle?: () => void;
  /** It goes somewhere rather than opening: no chevron, underlined on hover. */
  link?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const spinning = useSpinner(running);
  const body = (
    <>
      <span className={cn('flex size-4 flex-none items-center justify-center self-center', spinning && 'text-primary')}>
        {spinning ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : icon}
      </span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {onToggle && !link && (
        <ChevronRight className={cn('size-3.5 flex-none self-center opacity-60 transition-transform', open && 'rotate-90')} aria-hidden />
      )}
    </>
  );
  const cls = cn(
    'flex w-full min-w-0 items-baseline gap-2 py-0.5 text-left text-sm leading-5',
    tone === 'muted' && 'text-muted-foreground',
    tone === 'error' && 'text-destructive-text',
    tone === 'success' && 'text-success-text',
    onToggle && !link && 'rounded-sm hover:text-foreground',
    link && 'hover:[&>span:nth-child(2)]:underline',
    className,
  );
  if (!onToggle) return <div className={cls}>{body}</div>;
  return (
    <button type="button" onClick={onToggle} aria-expanded={link ? undefined : open} className={cls}>
      {body}
    </button>
  );
}

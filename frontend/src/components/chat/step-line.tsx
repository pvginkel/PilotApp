/** One muted line of a reply's steps: an icon, the words, a chevron when it opens. */

import { ChevronRight, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export function StepLine({
  icon,
  running,
  tone = 'muted',
  open,
  onToggle,
  link,
  children,
  className,
}: {
  icon: React.ReactNode;
  running?: boolean;
  tone?: 'muted' | 'error' | 'success';
  open?: boolean;
  onToggle?: () => void;
  /** It goes somewhere rather than opening: no chevron, underlined on hover. */
  link?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const body = (
    <>
      <span className={cn('flex size-4 flex-none translate-y-px items-center justify-center self-center', running && 'text-primary')}>
        {running ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : icon}
      </span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {onToggle && !link && (
        <ChevronRight className={cn('size-3.5 flex-none self-center opacity-60 transition-transform', open && 'rotate-90')} aria-hidden />
      )}
    </>
  );
  const cls = cn(
    'flex w-full min-w-0 items-baseline gap-2 py-0.5 text-left text-[13px] leading-5',
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

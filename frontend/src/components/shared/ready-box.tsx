/**
 * The box of a project that is ready for its next step (F48.1, D119; F48.3): a border, as wide as
 * what it holds and centred, around one small primary button and a muted line; above 900px the
 * button left of the line, at 900px and below above it (the mockup's `.create-ready`). Stuck, it
 * stands at the foot of what scrolls it, 12px up, lifted by a shadow over what scrolls under it,
 * and at that content's end once scrolled there (`.create-ready.stuck`).
 */

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface ReadyBoxProps {
  stuck?: boolean;
  testId: string;
  children: ReactNode;
}

export function ReadyBox({ stuck = false, testId, children }: ReadyBoxProps) {
  return (
    <div
      className={cn(
        'flex max-w-full items-center gap-3.5 self-center rounded-lg border py-2.5 pr-[18px] pl-2.5 text-center text-sm/[1.6] text-muted-foreground [@media(max-width:900px)]:flex-col [@media(max-width:900px)]:gap-2 [@media(max-width:900px)]:px-[18px] [@media(max-width:900px)]:pt-3.5 [@media(max-width:900px)]:pb-3',
        stuck && 'sticky bottom-3 z-[2] mt-3 bg-background shadow-[var(--shadow-md)]',
      )}
      data-testid={testId}
    >
      {children}
    </div>
  );
}

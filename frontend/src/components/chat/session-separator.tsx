/**
 * The chat's dividers, the timeline mockup's, a line each side of the words: where a chat closed,
 * "Chat closed · <time>" (F130.1), its cause not shown; and a day's first message, the day (F38.2).
 */

import { Time } from '@/components/shared/time';

export function SessionSeparator({ at }: { at: string }) {
  return (
    <div
      className="my-2 flex items-center gap-3 text-xs whitespace-nowrap text-muted-foreground before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border"
      data-testid="chat.closed"
    >
      <span>
        Chat closed · <Time at={at} format="clock" />
      </span>
    </div>
  );
}

export function DateDivider({ label }: { label: string }) {
  return (
    <div
      className="mt-2 flex items-center gap-3 text-xs font-semibold whitespace-nowrap text-muted-foreground before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border"
      data-testid="chat.day"
    >
      {label}
    </div>
  );
}

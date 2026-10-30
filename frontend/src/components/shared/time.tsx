/**
 * A time as every screen shows it (F114), in a format of `formatTime()`'s, the full stamp as its
 * tooltip.
 */

import { formatTime, type TimeFormat } from '@/lib/utils/time-format';

interface TimeProps {
  at: string;
  format?: Exclude<TimeFormat, 'full'>;
  testId?: string;
}

export function Time({ at, format = 'day', testId }: TimeProps) {
  return (
    <time dateTime={at} title={formatTime(at, 'full')} data-testid={testId}>
      {formatTime(at, format)}
    </time>
  );
}

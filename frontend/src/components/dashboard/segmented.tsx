/**
 * A choice of which one holds, in the dashboard's form of the app's segmented tabs (the mockup's
 * `.dash-seg`): a rounded track, the one that holds on the primary's tint; each a button, pressed
 * where it holds.
 */

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface Option<T> {
  value: T;
  label: ReactNode;
  testId: string;
}

interface SegmentedProps<T> {
  label: string;
  options: readonly Option<T>[];
  value: T;
  onChange: (value: T) => void;
}

export function Segmented<T>({ label, options, value, onChange }: SegmentedProps<T>) {
  return (
    <div className="dash-seg" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.testId}
          type="button"
          className={cn(option.value === value && 'on')}
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          data-testid={option.testId}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

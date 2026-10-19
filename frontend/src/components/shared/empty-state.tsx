/** An empty screen's word (F113): an icon and a line in the middle of where the content would be. */

import type { LucideIcon } from 'lucide-react';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  testId: string;
}

export function EmptyState({ icon: Icon, title, testId }: EmptyStateProps) {
  return (
    <div className="empty-state" data-testid={testId}>
      <Icon className="icon" aria-hidden="true" />
      <h2>{title}</h2>
    </div>
  );
}

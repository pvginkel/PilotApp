/**
 * The badge of the time a running work item still takes (F156.8), one form after a project's name
 * and after a running work item's time: a clock and the time left, "25 min", "1 h", "3 h", as the
 * server rounds it. At rest it is words alone, with no hover and no press. Longer than usual
 * (F156.7) it is the alert, red with the clock's alert: an em dash where the time stood, the time
 * left on a step the workflow marked, or the icon alone (status-labels.ts); the alert is a button
 * whose sentence drops under it on hover off a phone and on a press, closed by a press elsewhere,
 * Esc or the badge.
 */

import { useCallback, useState } from 'react';
import { Clock, ClockAlert } from 'lucide-react';
import { useDismiss } from '@/hooks/use-dismiss';
import type { components } from '@/lib/api/generated/types';
import { estimateAlertSentence, estimateBadge, estimateLeftLabel } from '@/lib/utils/status-labels';

type Estimate = components['schemas']['TimelineSchema.1fdd8ae.EstimateSchema'];

interface EtaBadgeProps {
  estimate: Estimate;
  /** The work item the alert's sentence names, in a project's head; none on the work item itself. */
  title?: string | null;
  testId: string;
}

export function EtaBadge({ estimate, title = null, testId }: EtaBadgeProps) {
  const { alert, text } = estimateBadge(estimate);
  if (alert) return <Alert text={text} says={estimateAlertSentence(estimate, title)} testId={testId} />;
  return (
    <div className="eta-wrap">
      {/* At rest the server gives the time left. */}
      <span className="eta-badge" role="img" aria-label={estimateLeftLabel(text!)} data-testid={testId}>
        <Clock className="icon" aria-hidden="true" />
        <span>{text}</span>
      </span>
    </div>
  );
}

function Alert({ text, says, testId }: { text: string | null; says: string; testId: string }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const anchor = useDismiss('plan', open, close);
  return (
    <div className="eta-wrap" ref={anchor}>
      <button
        type="button"
        className="eta-badge long"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label={says}
        data-testid={testId}
      >
        <ClockAlert className="icon" aria-hidden="true" />
        {text !== null && <span>{text}</span>}
      </button>
      <span className="eta-pop" role="tooltip" data-testid={`${testId}.says`}>
        {says}
      </span>
    </div>
  );
}

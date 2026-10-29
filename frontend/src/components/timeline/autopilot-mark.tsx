/**
 * The auto pilot mark (F4.4; ui-conventions, "The auto pilot mark"), on an open confirmation the
 * switch would answer while its project's auto pilot is off: in a confirmation card's head after
 * the time, in a confirmation block's head beside its kind, in a document inline and in the
 * overlay, and on a document's card as a chip counting such blocks. Its icon is the mockup's
 * (`mockup/autopilot-may-take.svg`, `apMark()`), used as it is there: Pilot's mark with Lucide's
 * zap, filled, at its foot, cut out of the mark; bare, in the time's grey, at a kind icon's size.
 */

import { useId } from 'react';
import { PILOT_MARK } from '@/components/shared/pilot-mark';

const ZAP =
  'M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z';
const ZAP_AT = 'translate(10.9 10.4) scale(.55)';

const HANDLES_THIS = 'Auto pilot will handle this for you';
const HANDLES_THESE = 'Auto pilot will handle these for you';

function AutopilotMayTake() {
  // A mask's id is the document's: each mark cuts its own bolt out with a mask of its own.
  const mask = `ap-knockout-${useId().replace(/[^\w-]/g, '')}`;
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <defs>
        <mask id={mask} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
          <rect width="24" height="24" fill="#fff" />
          <path transform={ZAP_AT} d={ZAP} fill="#000" stroke="#000" strokeWidth={10.9} strokeLinejoin="round" />
        </mask>
      </defs>
      <g mask={`url(#${mask})`}>
        {PILOT_MARK.map((d) => (
          <path key={d} d={d} />
        ))}
      </g>
      <path transform={ZAP_AT} d={ZAP} fill="currentColor" strokeWidth={1.82} />
    </svg>
  );
}

/** The mark in a head, its hover saying what it means. */
export function AutopilotMark({ testId }: { testId: string }) {
  return (
    <span className="ap-may" title={HANDLES_THIS} data-testid={testId}>
      <AutopilotMayTake />
    </span>
  );
}

/** A document card's chip beside its counts: the mark and "<count> auto pilot may take". */
export function AutopilotChip({ count }: { count: number }) {
  return (
    <span className="chip ap-may" title={count > 1 ? HANDLES_THESE : HANDLES_THIS} data-testid="timeline.item.autopilot-chip">
      <AutopilotMayTake />
      {`${count} auto pilot may take`}
    </span>
  );
}

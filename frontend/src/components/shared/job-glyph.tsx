/**
 * A button that starts Pilot's work (F59.3; ui-conventions, "Buttons that write or start work"):
 * under the mouse its icon gives way to Pilot's mark without the avatar's circle, Lucide's play at
 * its foot, hollow, in the mark's stroke, cut out of the mark with a clear gap around it, in the
 * icon's own colour (the mockup's `jobGlyph()`, `JOB_KNOCKOUT`, `.starts-work`). With no hover, a
 * phone's, the icon stays (shared.css).
 */

import { useId, type ReactNode } from 'react';
import { PILOT_MARK } from '@/components/shared/pilot-mark';

/** Lucide's play, as the mockup draws it. */
const PLAY = 'M6 3l14 9-14 9z';
const PLAY_AT = 'translate(12.2 11.6) scale(.5)';

function JobGlyph() {
  // A mask's id is the document's: each mark cuts its own play out with a mask of its own.
  const mask = `job-knockout-${useId().replace(/[^\w-]/g, '')}`;
  return (
    <svg
      className="icon job-glyph"
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
          <path transform={PLAY_AT} d={PLAY} fill="#000" stroke="#000" strokeWidth={13} strokeLinejoin="round" />
        </mask>
      </defs>
      <g mask={`url(#${mask})`}>
        {PILOT_MARK.map((d) => (
          <path key={d} d={d} />
        ))}
      </g>
      <path transform={PLAY_AT} d={PLAY} strokeWidth={4} />
    </svg>
  );
}

/** `icon`, a button's own, with the mark that takes its place under the mouse; the button's direct child. */
export function StartsWork({ children: icon }: { children: ReactNode }) {
  return (
    <span className="starts-work">
      {icon}
      <JobGlyph />
    </span>
  );
}

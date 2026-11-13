/**
 * The cancelled mark (F13.1; ui-conventions, "Done lines"), in the kind icon's place on the line of
 * an item done `cancelled`: the item's kind icon with a small cross at its foot, cut out of the icon
 * as the auto pilot mark's bolt is (the mockup's `crossedMark()`, `X_KNOCKOUT`).
 */

import { useId } from 'react';
import type { LucideIcon } from 'lucide-react';

export function CancelledMark({ icon: Icon }: { icon: LucideIcon }) {
  // A mask's id is the document's: each mark cuts its own cross out with a mask of its own.
  const mask = `x-knockout-${useId().replace(/[^\w-]/g, '')}`;
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
          <circle cx="18.5" cy="18.5" r="7" fill="#000" />
        </mask>
      </defs>
      <g mask={`url(#${mask})`}>
        {/* Lucide's icon as a nested drawing, on the mark's own 24 by 24 grid. */}
        <Icon width={24} height={24} />
      </g>
      <path d="m15 15 7 7M22 15l-7 7" />
    </svg>
  );
}

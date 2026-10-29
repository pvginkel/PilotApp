/**
 * An avatar (F106, F132): a person's initials in their palette colour with their full name as the
 * tooltip, or Pilot's mark in the same circle.
 */

import { UserRound } from 'lucide-react';
import { PILOT_MARK } from '@/components/shared/pilot-mark';
import { cn } from '@/lib/utils';

// app-theme.css's --avatar-1 to --avatar-6.
const PALETTE_SIZE = 6;

interface Person {
  name: string;
  /** Null for a name with nothing to take them from: a user icon stands in. */
  initials: string | null;
  /** Null until the person takes a slot, at their first sign-in. */
  slot: number | null;
}

interface AvatarProps {
  who: Person | 'pilot';
  /** 24px, or 20px for an answer's line; 32px by default. */
  size?: 'sm' | 'xs';
}

export function Avatar({ who, size }: AvatarProps) {
  if (who === 'pilot') {
    return (
      <span className={cn('avatar pilot', size)} title="Pilot">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          {PILOT_MARK.map((d) => (
            <path key={d} d={d} />
          ))}
        </svg>
      </span>
    );
  }
  // Slots count from 1: slot n takes the palette's colour (n - 1) modulo its size.
  const colour = who.slot === null ? undefined : ((who.slot - 1) % PALETTE_SIZE) + 1;
  return (
    <span className={cn('avatar', size)} data-colour={colour} title={who.name}>
      {who.initials ?? <UserRound className="icon" aria-hidden="true" />}
    </span>
  );
}

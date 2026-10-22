/**
 * An avatar (F106, F132): a person's initials in their palette colour with their full name as the
 * tooltip, or Pilot's mark in the same circle.
 */

import { UserRound } from 'lucide-react';
import { cn } from '@/lib/utils';

// app-theme.css's --avatar-1 to --avatar-6.
const PALETTE_SIZE = 6;

// Lucide's user-round under a pilot's cap (ui-conventions.md, "Pilot's mark and the avatars").
const PILOT_MARK = ['M4.5 4c3-2.5 12-2.5 15 0L17 6H7z', 'M7.42 6A5 5 0 1 0 16.58 6', 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2'];

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

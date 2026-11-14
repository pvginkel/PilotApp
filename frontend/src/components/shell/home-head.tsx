/**
 * On a phone, the home's head (F98.6, F111): the top bar's block of colour, a project head's
 * height, Pilot's icon on its white tile and its name, white on the primary, and the avatar, which
 * opens the profile menu (F126); over the handle step too (F137). And the arrow to the home (F2.8),
 * a head's first part on every other screen, or alone at the top-left, where a head's stands, on a
 * screen with no head.
 */

import { ArrowLeft } from 'lucide-react';
import { ProfileMenu } from '@/components/shell/profile-menu';
import type { Self } from '@/hooks/use-self';

export function HomeHead({ self }: { self: Self }) {
  return (
    <div className="home-head" data-testid="shell.home-head">
      <div className="brand">
        <img className="logo" src="/logo.png" alt="" />
        Pilot
      </div>
      <span className="grow" />
      <ProfileMenu self={self} />
    </div>
  );
}

export function HomeButton({ onHome }: { onHome: () => void }) {
  return (
    <button
      type="button"
      className="btn btn-ghost btn-icon head-home"
      title="All projects"
      aria-label="All projects"
      onClick={onHome}
      data-testid="shell.home-button"
    >
      <ArrowLeft className="icon" aria-hidden="true" />
    </button>
  );
}

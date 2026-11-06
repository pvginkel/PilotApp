/**
 * The top bar (F111), off a phone: at the narrow width the drawer's toggle first (F98.2), the
 * phone's drawer button in the bar's white; the logo on its tile and the name, the gold bar's badges
 * after it, and the signed-in person's avatar, which opens the profile menu (F126). At the handle
 * step it has no toggle and no badge, and its menu no Profile. The phone has none (F98.3): its
 * drawer opens on its colours.
 */

import { DrawerToggle, type Drawer } from '@/components/shell/drawer';
import { GoldBadges } from '@/components/shell/gold-bar';
import { ProfileMenu } from '@/components/shell/profile-menu';
import type { Condition } from '@/hooks/use-conditions';
import type { Self } from '@/hooks/use-self';

interface TopBarProps {
  self: Self | undefined;
  /** The project list's drawer, at the narrow width once the app is open; none otherwise. */
  drawer: Drawer | null;
  /** What holds all work, none while the app is not open. */
  conditions: Condition[];
}

export function TopBar({ self, drawer, conditions }: TopBarProps) {
  return (
    <header className="topbar" data-testid="app-shell.topbar">
      {drawer && <DrawerToggle drawer={drawer} />}
      <div className="brand">
        <img className="logo" src="/logo.png" alt="" />
        Pilot
      </div>
      <GoldBadges conditions={conditions} />
      <div className="spacer" />
      {self && <ProfileMenu self={self} />}
    </header>
  );
}

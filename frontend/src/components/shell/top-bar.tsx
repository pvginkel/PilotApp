/**
 * The top bar (F111): the drawer toggle on a narrow window, the logo on its tile and the name, and
 * the signed-in person's avatar, which opens the profile menu (F126). At the handle step it has
 * no drawer to toggle, and its menu no Profile.
 */

import { useNavigate } from '@tanstack/react-router';
import { LogOut, Menu as MenuIcon, UserRound } from 'lucide-react';
import { Avatar } from '@/components/shared/avatar';
import { Menu, MenuItem } from '@/components/shared/menu';
import { useAuthContext } from '@/contexts/auth-context';
import { isPerson, type Self } from '@/hooks/use-self';
import { THEMES, type Theme } from '@/lib/browser-state';
import { useTheme } from '@/lib/theme';

const THEME_LABELS: Record<Theme, string> = { system: 'System', light: 'Light', dark: 'Dark' };

interface TopBarProps {
  self: Self | undefined;
  /** Null while the app is not open. */
  drawer: { open: boolean; toggle: () => void } | null;
}

export function TopBar({ self, drawer }: TopBarProps) {
  return (
    <header className="topbar" data-testid="app-shell.topbar">
      {drawer && (
        <button
          type="button"
          className="drawer-toggle"
          aria-label="Projects"
          aria-expanded={drawer.open}
          onClick={drawer.toggle}
          data-testid="shell.drawer-toggle"
        >
          <MenuIcon className="icon" aria-hidden="true" />
        </button>
      )}
      <div className="brand">
        <img className="logo" src="/logo.png" alt="" />
        Pilot
      </div>
      <div className="spacer" />
      {self && <ProfileMenu self={self} />}
    </header>
  );
}

// The template's user dropdown in the mockup's avatar, as FieldnotesApp has it: the name, the
// theme, Profile and Sign out, under the template's test ids, which its sign-in specs look for.
function ProfileMenu({ self }: { self: Self }) {
  const { logout } = useAuthContext();
  const navigate = useNavigate();
  const [theme, chooseTheme] = useTheme();
  const name = self.name ?? 'Unknown User';
  return (
    <Menu
      label="Profile"
      testId="app-shell.topbar.user.dropdown"
      trigger={({ open, toggle }) => (
        <button
          type="button"
          className="avatar-btn"
          aria-label={name}
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={toggle}
          data-testid="app-shell.topbar.user"
        >
          <Avatar who={{ name, initials: self.initials, slot: self.avatar_slot }} />
          <span className="sr-only" data-testid="app-shell.topbar.user.name">
            {name}
          </span>
        </button>
      )}
    >
      <div className="menu-name" data-testid="shell.profile.name">
        {name}
      </div>
      <label className="menu-field">
        Theme
        <select
          value={theme}
          onChange={(event) => chooseTheme(event.target.value as Theme)}
          data-testid="shell.profile.theme"
        >
          {THEMES.map((option) => (
            <option key={option} value={option}>
              {THEME_LABELS[option]}
            </option>
          ))}
        </select>
      </label>
      <hr className="menu-rule" />
      {isPerson(self) && (
        <MenuItem icon={UserRound} onSelect={() => navigate({ to: '/profile' })} testId="shell.profile.page">
          Profile
        </MenuItem>
      )}
      <MenuItem icon={LogOut} onSelect={logout} testId="app-shell.topbar.user.logout">
        Sign out
      </MenuItem>
    </Menu>
  );
}

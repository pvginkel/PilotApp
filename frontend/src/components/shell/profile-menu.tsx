/**
 * The profile menu (F126), opened from the signed-in person's avatar: off a phone in the top bar,
 * on a phone in the drawer's head. The template's user dropdown in the mockup's avatar, as
 * FieldnotesApp has it: the name, the theme, Profile and Sign out, under the template's test ids,
 * which its sign-in specs look for. At the handle step it has no Profile. A person's Sign out
 * removes this browser's subscription first (F146.3); at the handle step there is none. Its foot
 * is the short hash of the commit the page is built from.
 */

import { useNavigate } from '@tanstack/react-router';
import { LogOut, UserRound } from 'lucide-react';
import { Avatar } from '@/components/shared/avatar';
import { Menu, MenuItem } from '@/components/shared/menu';
import { useAuthContext } from '@/contexts/auth-context';
import { useSignOut } from '@/hooks/use-device-notifications';
import { isPerson, type Self } from '@/hooks/use-self';
import { THEMES, type Theme } from '@/lib/browser-state';
import { useTheme } from '@/lib/theme';

const THEME_LABELS: Record<Theme, string> = { system: 'System', light: 'Light', dark: 'Dark' };

const COMMIT = import.meta.env.VITE_BUILD_COMMIT.slice(0, 7);

export function ProfileMenu({ self }: { self: Self }) {
  const { logout } = useAuthContext();
  const signOut = useSignOut();
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
      <MenuItem icon={LogOut} onSelect={isPerson(self) ? signOut : logout} testId="app-shell.topbar.user.logout">
        Sign out
      </MenuItem>
      <div className="menu-foot" data-testid="shell.profile.version">
        {COMMIT}
      </div>
    </Menu>
  );
}

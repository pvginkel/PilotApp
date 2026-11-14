/**
 * The project list's drawer at the narrow width (F98.2): its toggle, the top bar's first part
 * (`top-bar.tsx`). A wide window has no drawer, and a phone has its home in its place (F98.6).
 */

import { Menu as MenuIcon } from 'lucide-react';

export interface Drawer {
  open: boolean;
  toggle: () => void;
}

export function DrawerToggle({ drawer }: { drawer: Drawer }) {
  return (
    <button
      type="button"
      className="btn btn-ghost btn-icon head-drawer"
      title="Projects"
      aria-label="Projects"
      aria-expanded={drawer.open}
      onClick={drawer.toggle}
      data-testid="shell.drawer-toggle"
    >
      <MenuIcon className="icon" aria-hidden="true" />
    </button>
  );
}

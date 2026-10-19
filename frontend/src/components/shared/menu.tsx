/**
 * A menu that drops from its button (the mockup's `.menu-pop`): it closes on a press outside it,
 * on Esc, and when one of its items is chosen.
 */

import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { useDismiss } from '@/hooks/use-dismiss';
import { cn } from '@/lib/utils';

const CloseMenu = createContext<() => void>(() => undefined);

interface MenuProps {
  /** The menu's accessible name. */
  label: string;
  /** The class of the box that holds the button and the menu. */
  anchorClassName?: string;
  testId: string;
  trigger: (state: { open: boolean; toggle: () => void }) => ReactNode;
  children: ReactNode;
}

export function Menu({ label, anchorClassName, testId, trigger, children }: MenuProps) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const anchor = useDismiss('menu', open, close);

  return (
    <div className={cn('menu-anchor', anchorClassName)} ref={anchor}>
      {trigger({ open, toggle: () => setOpen(!open) })}
      {open && (
        <div className="menu-pop" role="menu" aria-label={label} data-testid={testId}>
          <CloseMenu.Provider value={close}>{children}</CloseMenu.Provider>
        </div>
      )}
    </div>
  );
}

interface MenuItemProps {
  icon: LucideIcon;
  onSelect: () => void;
  testId: string;
  children: ReactNode;
}

export function MenuItem({ icon: Icon, onSelect, testId, children }: MenuItemProps) {
  const close = useContext(CloseMenu);
  return (
    <button
      type="button"
      role="menuitem"
      className="menu-item"
      onClick={() => {
        close();
        onSelect();
      }}
      data-testid={testId}
    >
      <Icon className="icon" aria-hidden="true" />
      {children}
    </button>
  );
}

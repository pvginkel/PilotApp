/**
 * The drawer's button (F98.3): on a phone the first part of a screen's head, or, on a screen with
 * no head, alone at the top-left, where a head's stands. Off a phone no screen draws it: at the
 * narrow width it is the top bar's (F98.2, `top-bar.tsx`), and a wide window has no drawer.
 */

import { createContext, useCallback, useContext, useLayoutEffect, useState, type ReactNode } from 'react';
import { Menu as MenuIcon } from 'lucide-react';

export interface Drawer {
  open: boolean;
  toggle: () => void;
}

const DrawerContext = createContext<Drawer | null>(null);
/** Takes the button into a head for as long as the head is drawn: returns its release. */
const ClaimContext = createContext<(() => () => void) | null>(null);

/** The drawer's button for the screen it holds: alone at its top while no head draws it. */
export function DrawerProvider({ drawer, children }: { drawer: Drawer; children: ReactNode }) {
  const [heads, setHeads] = useState(0);
  const claim = useCallback(() => {
    setHeads((count) => count + 1);
    return () => setHeads((count) => count - 1);
  }, []);
  return (
    <DrawerContext.Provider value={drawer}>
      <ClaimContext.Provider value={claim}>
        {heads === 0 && (
          <div className="drawer-bar">
            <DrawerToggle drawer={drawer} />
          </div>
        )}
        {children}
      </ClaimContext.Provider>
    </DrawerContext.Provider>
  );
}

/** The drawer's button as a head's first part: none off a phone. */
export function DrawerButton() {
  const drawer = useContext(DrawerContext);
  const claim = useContext(ClaimContext);
  // Before the paint, so that the button never stands twice.
  useLayoutEffect(() => claim?.(), [claim]);
  return drawer && <DrawerToggle drawer={drawer} />;
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

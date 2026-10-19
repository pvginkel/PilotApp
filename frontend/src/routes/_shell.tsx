/**
 * The frame every screen sits in: the top bar, the side column for the project list and the
 * centre, where the child route shows. Under the mockup's breakpoint the side column is a drawer
 * over the centre (F98.3), opened from the top bar and closed by its scrim or by going elsewhere.
 */

import { useState } from 'react';
import { createFileRoute, Outlet, useRouterState } from '@tanstack/react-router';
import { KeysList } from '@/components/shell/keys-list';
import { TopBar } from '@/components/shell/top-bar';
import { useSelf } from '@/hooks/use-self';
import { useShellKeys } from '@/lib/keys';
import { startTheme } from '@/lib/theme';

startTheme();

export const Route = createFileRoute('/_shell')({
  component: Shell,
});

function Shell() {
  const { data: self } = useSelf();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  // The drawer is open on the page it was opened on, so going elsewhere closes it.
  const [drawerOn, setDrawerOn] = useState<string | null>(null);
  const drawerOpen = drawerOn === pathname;
  const [keysList, setKeysList] = useState(false);
  useShellKeys(() => setKeysList(!keysList));

  return (
    <>
      <TopBar self={self} drawerOpen={drawerOpen} onDrawer={() => setDrawerOn(drawerOpen ? null : pathname)} />
      <div className="app" data-drawer={drawerOpen ? 'open' : 'closed'} data-testid="shell.app">
        <nav className="tabs" aria-label="Projects" data-testid="shell.side" />
        <div className="drawer-scrim" onClick={() => setDrawerOn(null)} data-testid="shell.scrim" />
        <main className="centre" data-testid="shell.centre">
          <Outlet />
        </main>
      </div>
      {keysList && <KeysList onClose={() => setKeysList(false)} />}
    </>
  );
}

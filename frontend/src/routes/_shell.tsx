/**
 * The frame every screen sits in: the top bar, the side column with the gold bar over the project
 * list, and the centre, where the child route shows. Under the mockup's breakpoint the side column
 * is a drawer over the centre (F98.3), opened from the top bar and closed by its scrim or by going
 * elsewhere, and the gold bar spans the window under the top bar.
 * At a first sign-in the handle step stands in their place (F137): no screen opens before it.
 * Every text under the side column and the centre links through the link settings read here.
 */

import { useState } from 'react';
import { createFileRoute, Outlet, useRouterState } from '@tanstack/react-router';
import { HandleStep } from '@/components/people/handle-step';
import { GoldBar } from '@/components/shell/gold-bar';
import { ProjectColumn } from '@/components/projects/project-column';
import { KeysList } from '@/components/shell/keys-list';
import { LinksProvider } from '@/components/shared/linked-text';
import { TopBar } from '@/components/shell/top-bar';
import { useProjectEvents } from '@/hooks/use-project-events';
import { isPerson, PersonProvider, useSelf } from '@/hooks/use-self';
import { useShellKeys } from '@/lib/keys';
import { registerServiceWorker } from '@/lib/service-worker';
import { startTheme } from '@/lib/theme';

startTheme();
registerServiceWorker();

export const Route = createFileRoute('/_shell')({
  component: Shell,
});

function Shell() {
  const { data: self } = useSelf();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  // The drawer is open on the page it was opened on, and going elsewhere closes it: coming back
  // to that page, by Back or a link, finds it closed.
  const [drawerOn, setDrawerOn] = useState<string | null>(null);
  if (drawerOn !== null && drawerOn !== pathname) setDrawerOn(null);
  const drawerOpen = drawerOn === pathname;
  const [keysList, setKeysList] = useState(false);
  useShellKeys(() => setKeysList(!keysList));
  useProjectEvents();
  const person = self !== undefined && isPerson(self) ? self : null;

  return (
    <>
      <TopBar
        self={self}
        drawer={person && { open: drawerOpen, toggle: () => setDrawerOn(drawerOpen ? null : pathname) }}
      />
      {self !== undefined && person === null && <HandleStep self={self} />}
      {person !== null && (
        <PersonProvider value={person}>
          <LinksProvider>
            <div className="app" data-drawer={drawerOpen ? 'open' : 'closed'} data-testid="shell.app">
              <GoldBar />
              <nav className="tabs" aria-label="Projects" data-testid="shell.side">
                <ProjectColumn />
              </nav>
              <div className="drawer-scrim" onClick={() => setDrawerOn(null)} data-testid="shell.scrim" />
              <main className="centre" data-testid="shell.centre">
                <Outlet />
              </main>
            </div>
          </LinksProvider>
        </PersonProvider>
      )}
      {keysList && <KeysList onClose={() => setKeysList(false)} />}
    </>
  );
}

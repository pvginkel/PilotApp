/**
 * The frame every screen sits in, the child route showing in its centre: off a phone the top bar
 * over the side column and the centre (`DeskFrame`), the side column at the narrow width a drawer
 * over the centre, opened from the top bar and closed by its scrim or by going elsewhere (F98.2);
 * on a phone no top bar and no side column, the project list the home (`PhoneFrame`, F98.3).
 * At a first sign-in the handle step stands in their place (F137): no screen opens before it.
 * Off a phone the dashboard is the second screen (F160.2), drawn beside the frame once an address
 * first names it, its code loaded then, and never taken down: neither the router nor a change of
 * frame takes it down. The screen out of sight lies under the one that shows, in the same box,
 * out of the flow, its visibility off and inert, so that its place and its scroll are kept.
 * The page closes the notifications of what it shows on its device and beats while its person is
 * active in it (`use-app-page.ts`).
 * Every text under the side column and the centre links through the link settings read here.
 * Once it shows, a route keeps the screen showing while it reads its own (`screen-reads.ts`).
 * While the connection to the server is down or slow, the page lies under its tint (F149).
 */

import { lazy, Suspense, useEffect, useState } from 'react';
import { createFileRoute, Outlet, useRouterState } from '@tanstack/react-router';
import { ConnectionTint } from '@/components/shell/connection-tint';
import { DeskFrame } from '@/components/shell/desk-frame';
import { KeysList } from '@/components/shell/keys-list';
import { PhoneFrame } from '@/components/shell/phone-frame';
import { useAppPage } from '@/hooks/use-app-page';
import { useConditions } from '@/hooks/use-conditions';
import { useNarrow } from '@/hooks/use-narrow';
import { usePhone } from '@/hooks/use-phone';
import { useProjectEvents } from '@/hooks/use-project-events';
import { useScreens } from '@/hooks/use-screens';
import { isPerson, useSelf } from '@/hooks/use-self';
import { useShellKeys } from '@/lib/keys';
import { screenShown } from '@/lib/screen-reads';
import { registerServiceWorker } from '@/lib/service-worker';
import { startTheme } from '@/lib/theme';

startTheme();
registerServiceWorker();

const DashboardScreen = lazy(() => import('@/components/dashboard/dashboard-screen').then((module) => ({ default: module.DashboardScreen })));

export const Route = createFileRoute('/_shell')({
  component: Shell,
});

function Shell() {
  const { data: self } = useSelf();
  useEffect(screenShown, []);
  useAppPage(self);
  const phone = usePhone();
  const narrow = useNarrow();
  const screens = useScreens(!phone && self !== undefined && isPerson(self));
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  // The drawer is open on the page it was opened on, and going elsewhere closes it: coming back
  // to that page, by Back or a link, finds it closed.
  const [drawerOn, setDrawerOn] = useState<string | null>(null);
  if (drawerOn !== null && drawerOn !== pathname) setDrawerOn(null);
  const drawerOpen = drawerOn === pathname;
  const drawer = {
    open: drawerOpen,
    toggle: () => setDrawerOn(drawerOpen ? null : pathname),
    close: () => setDrawerOn(null),
  };
  const [keysList, setKeysList] = useState(false);
  useShellKeys(() => setKeysList(!keysList));
  useProjectEvents();
  const conditions = useConditions();

  return (
    <>
      <div className="screen-stack" data-testid="shell.screen-stack">
        {phone ? (
          <PhoneFrame self={self} conditions={conditions}>
            <Outlet />
          </PhoneFrame>
        ) : (
          <DeskFrame self={self} drawer={narrow ? drawer : null} screens={screens} conditions={conditions}>
            <Outlet />
          </DeskFrame>
        )}
        {screens.drawn && (
          <Suspense fallback={null}>
            <DashboardScreen shown={screens.shown === 'dashboard'} />
          </Suspense>
        )}
      </div>
      {keysList && <KeysList onClose={() => setKeysList(false)} />}
      <ConnectionTint />
    </>
  );
}

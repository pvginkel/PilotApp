/**
 * The frame every screen sits in, the child route showing in its centre: off a phone the top bar
 * over the side column and the centre (`DeskFrame`); on a phone no top bar, the side column a
 * drawer over the centre, closed by its scrim or by going elsewhere (`PhoneFrame`, F98.3).
 * At a first sign-in the handle step stands in their place (F137): no screen opens before it.
 * Every text under the side column and the centre links through the link settings read here.
 */

import { useState } from 'react';
import { createFileRoute, Outlet, useRouterState } from '@tanstack/react-router';
import { DeskFrame } from '@/components/shell/desk-frame';
import { KeysList } from '@/components/shell/keys-list';
import { PhoneFrame } from '@/components/shell/phone-frame';
import { useConditions } from '@/hooks/use-conditions';
import { usePhone } from '@/hooks/use-phone';
import { useProjectEvents } from '@/hooks/use-project-events';
import { useSelf } from '@/hooks/use-self';
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
  const phone = usePhone();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  // The drawer is open on the page it was opened on, and going elsewhere closes it: coming back
  // to that page, by Back or a link, finds it closed.
  const [drawerOn, setDrawerOn] = useState<string | null>(null);
  if (drawerOn !== null && drawerOn !== pathname) setDrawerOn(null);
  const drawerOpen = drawerOn === pathname;
  const [keysList, setKeysList] = useState(false);
  useShellKeys(() => setKeysList(!keysList));
  useProjectEvents();
  const conditions = useConditions();

  return (
    <>
      {phone ? (
        <PhoneFrame
          self={self}
          drawer={{
            open: drawerOpen,
            toggle: () => setDrawerOn(drawerOpen ? null : pathname),
            close: () => setDrawerOn(null),
          }}
          conditions={conditions}
        >
          <Outlet />
        </PhoneFrame>
      ) : (
        <DeskFrame self={self} conditions={conditions}>
          <Outlet />
        </DeskFrame>
      )}
      {keysList && <KeysList onClose={() => setKeysList(false)} />}
    </>
  );
}

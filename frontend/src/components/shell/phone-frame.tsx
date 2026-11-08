/**
 * The frame on a phone (F98.3, F111): no top bar. The gold bar spans the page's top, over the
 * centre, and over it the offer of the browser's notifications, a bar of its own (F146.2); under
 * them the drawer lies over the centre, the screen's head included, behind its scrim, and opens on
 * the top bar's block of colour: Pilot's icon and name, white on the primary, and the avatar,
 * which opens the profile menu (F126). The drawer's button is the screen's own (`DrawerButton`).
 * The browser's own bar takes the page's colour. At a first sign-in the handle step stands under
 * the block of colour, which opens no drawer (F137). The loading bar lies at the page's top.
 */

import type { ReactNode } from 'react';
import { HandleStep } from '@/components/people/handle-step';
import { ProjectColumn } from '@/components/projects/project-column';
import { LinksProvider } from '@/components/shared/linked-text';
import { DrawerProvider, type Drawer } from '@/components/shell/drawer';
import { GoldBar } from '@/components/shell/gold-bar';
import { LoadingBar } from '@/components/shell/loading-bar';
import { NotificationsOffer } from '@/components/shell/notifications-offer';
import { ProfileMenu } from '@/components/shell/profile-menu';
import type { Condition } from '@/hooks/use-conditions';
import { isPerson, PersonProvider, type Self } from '@/hooks/use-self';
import { useBrowserBarInPageColour } from '@/lib/theme';

interface PhoneFrameProps {
  self: Self | undefined;
  drawer: Drawer & { close: () => void };
  conditions: Condition[];
  children: ReactNode;
}

export function PhoneFrame({ self, drawer, conditions, children }: PhoneFrameProps) {
  useBrowserBarInPageColour();
  if (self === undefined) return null;
  if (!isPerson(self)) {
    return (
      <>
        <DrawerHead self={self} />
        <HandleStep self={self} />
      </>
    );
  }
  return (
    <PersonProvider value={self}>
      <LinksProvider>
        <NotificationsOffer handle={self.handle} />
        <div className="app" data-drawer={drawer.open ? 'open' : 'closed'} data-testid="shell.app">
          <LoadingBar />
          <GoldBar conditions={conditions} />
          <nav className="tabs" aria-label="Projects" data-testid="shell.side">
            <DrawerHead self={self} />
            <ProjectColumn />
          </nav>
          <div className="drawer-scrim" onClick={drawer.close} data-testid="shell.scrim" />
          <main className="centre" data-testid="shell.centre">
            <DrawerProvider drawer={drawer}>{children}</DrawerProvider>
          </main>
        </div>
      </LinksProvider>
    </PersonProvider>
  );
}

/** The top bar's block of colour, at the drawer's top, or over the handle step. */
function DrawerHead({ self }: { self: Self }) {
  return (
    <div className="drawer-head" data-testid="shell.drawer-head">
      <div className="brand">
        <img className="logo" src="/logo.png" alt="" />
        Pilot
      </div>
      <span className="grow" />
      <ProfileMenu self={self} />
    </div>
  );
}

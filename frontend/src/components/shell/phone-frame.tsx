/**
 * The frame on a phone (F98.3, F111): no top bar and no drawer. The gold bar spans the page's top,
 * over the centre, and over it the offer of the browser's notifications, a bar of its own (F146.2);
 * the centre holds the home, the project list (F98.6), or a screen opened from it. The browser's
 * own bar takes the bottom tabs' tint, by `index.html`'s theme-colors. At a first sign-in the
 * handle step stands under the home's head (F137). The loading bar lies at the page's top.
 */

import type { ReactNode } from 'react';
import { HandleStep } from '@/components/people/handle-step';
import { LinksProvider } from '@/components/shared/linked-text';
import { GoldBar } from '@/components/shell/gold-bar';
import { HomeHead } from '@/components/shell/home-head';
import { LoadingBar } from '@/components/shell/loading-bar';
import { NotificationsOffer } from '@/components/shell/notifications-offer';
import type { Condition } from '@/hooks/use-conditions';
import { isPerson, PersonProvider, type Self } from '@/hooks/use-self';

interface PhoneFrameProps {
  self: Self | undefined;
  conditions: Condition[];
  children: ReactNode;
}

export function PhoneFrame({ self, conditions, children }: PhoneFrameProps) {
  if (self === undefined) return null;
  if (!isPerson(self)) {
    return (
      <>
        <HomeHead self={self} />
        <HandleStep self={self} />
      </>
    );
  }
  return (
    <PersonProvider value={self}>
      <LinksProvider>
        <NotificationsOffer handle={self.handle} />
        <div className="app" data-testid="shell.app">
          <LoadingBar />
          <GoldBar conditions={conditions} />
          <main className="centre" data-testid="shell.centre">
            {children}
          </main>
        </div>
      </LinksProvider>
    </PersonProvider>
  );
}

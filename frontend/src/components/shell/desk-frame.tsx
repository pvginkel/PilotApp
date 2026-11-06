/**
 * The frame off a phone (F98.1, F111): the top bar with the gold bar's badges, the side column with
 * the project list beside the centre. At the narrow width (F98.2) the side column is the phone's
 * drawer over the centre, behind its scrim, opened from the top bar's toggle, under the top bar.
 * At a first sign-in the handle step stands under the top bar in their place (F137).
 */

import type { ReactNode } from 'react';
import { HandleStep } from '@/components/people/handle-step';
import { ProjectColumn } from '@/components/projects/project-column';
import { LinksProvider } from '@/components/shared/linked-text';
import type { Drawer } from '@/components/shell/drawer';
import { TopBar } from '@/components/shell/top-bar';
import type { Condition } from '@/hooks/use-conditions';
import { isPerson, PersonProvider, type Self } from '@/hooks/use-self';

interface DeskFrameProps {
  self: Self | undefined;
  /** The project list's drawer, at the narrow width; none on a wide window. */
  drawer: (Drawer & { close: () => void }) | null;
  conditions: Condition[];
  children: ReactNode;
}

export function DeskFrame({ self, drawer, conditions, children }: DeskFrameProps) {
  const person = self !== undefined && isPerson(self) ? self : null;
  return (
    <>
      <TopBar self={self} drawer={person && drawer} conditions={person ? conditions : []} />
      {self !== undefined && person === null && <HandleStep self={self} />}
      {person !== null && (
        <PersonProvider value={person}>
          <LinksProvider>
            <div className="app" data-drawer={drawer === null ? undefined : drawer.open ? 'open' : 'closed'} data-testid="shell.app">
              <nav className="tabs" aria-label="Projects" data-testid="shell.side">
                <ProjectColumn />
              </nav>
              {drawer !== null && <div className="drawer-scrim" onClick={drawer.close} data-testid="shell.scrim" />}
              <main className="centre" data-testid="shell.centre">
                {children}
              </main>
            </div>
          </LinksProvider>
        </PersonProvider>
      )}
    </>
  );
}

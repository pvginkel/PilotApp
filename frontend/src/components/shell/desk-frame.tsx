/**
 * The frame off a phone (F98.1, F111): the top bar with the gold bar's badges, the side column with
 * the project list beside the centre. At a first sign-in the handle step stands under the top bar
 * in their place (F137).
 */

import type { ReactNode } from 'react';
import { HandleStep } from '@/components/people/handle-step';
import { ProjectColumn } from '@/components/projects/project-column';
import { LinksProvider } from '@/components/shared/linked-text';
import { TopBar } from '@/components/shell/top-bar';
import type { Condition } from '@/hooks/use-conditions';
import { isPerson, PersonProvider, type Self } from '@/hooks/use-self';

interface DeskFrameProps {
  self: Self | undefined;
  conditions: Condition[];
  children: ReactNode;
}

export function DeskFrame({ self, conditions, children }: DeskFrameProps) {
  const person = self !== undefined && isPerson(self) ? self : null;
  return (
    <>
      <TopBar self={self} conditions={person ? conditions : []} />
      {self !== undefined && person === null && <HandleStep self={self} />}
      {person !== null && (
        <PersonProvider value={person}>
          <LinksProvider>
            <div className="app" data-testid="shell.app">
              <nav className="tabs" aria-label="Projects" data-testid="shell.side">
                <ProjectColumn />
              </nav>
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

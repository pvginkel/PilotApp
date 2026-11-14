/**
 * The phone's home (F98.6), at the bare address: under the gold bar its head, the top bar's block
 * of colour (`home-head.tsx`), and the project list as the side column has it (F1), the plus at its
 * head, each group closed until opened, no project marked as on screen. A row opens its project's
 * Timeline over the home (F98.3). Archived, from the list head's menu, is a view of its own pushed
 * over the home and its head (F128.2, F98.4), an entry in the browser's history, so that a reload
 * keeps it: its arrow back, Esc and Back take it off.
 */

import { useRef, type ReactNode } from 'react';
import { useNavigate, useRouter, useRouterState } from '@tanstack/react-router';
import { ArrowLeft } from 'lucide-react';
import { ArchivedRows, ProjectList } from '@/components/projects/project-column';
import { ScrollBar } from '@/components/shared/scroll-bar';
import { HomeHead } from '@/components/shell/home-head';
import { usePerson } from '@/hooks/use-self';
import { useEscape } from '@/lib/keys';

export function PhoneHome() {
  const person = usePerson();
  const archived = useRouterState({ select: (state) => state.location.state.homeView === 'archived' });
  const navigate = useNavigate();
  if (archived) return <ArchivedView />;
  return (
    <div className="home" data-testid="home">
      <HomeHead self={person} />
      <HomeList label="Projects">
        <ProjectList onArchived={() => void navigate({ to: '/', state: { homeView: 'archived' } })} />
      </HomeList>
    </div>
  );
}

function ArchivedView() {
  const router = useRouter();
  const back = () => router.history.back();
  useEscape('overlay', true, back);
  return (
    <div className="home" data-testid="projects.archived">
      <header className="feed-head phone-head">
        <button
          type="button"
          className="btn btn-ghost btn-icon head-home"
          title="Back to the projects"
          aria-label="Back to the projects"
          onClick={back}
          data-testid="projects.archived.back"
        >
          <ArrowLeft className="icon" aria-hidden="true" />
        </button>
        <h1>Archived</h1>
      </header>
      <HomeList label="Archived projects">
        <ArchivedRows />
      </HomeList>
    </div>
  );
}

/** The home's list, or the Archived view's, scrolling under its drawn bar. */
function HomeList({ label, children }: { label: string; children: ReactNode }) {
  const list = useRef<HTMLElement>(null);
  return (
    <div className="scroll-frame">
      <nav ref={list} className="home-list scroll-view" aria-label={label} data-testid="home.list">
        {children}
      </nav>
      <ScrollBar view={list} testId="home.list.scrollbar" />
    </div>
  );
}

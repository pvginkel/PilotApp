/**
 * A project's tab (F1.1, F1.2): its name, its ticket id and its status line, at most two lines,
 * opening the project at its own address, which off a phone moves on to the tab it was left on
 * (F1.6); its status icon, the pause (F1.3, F141); and the badge counting the items waiting on the
 * person, orange when one of them is urgent (F1.4). The tab of the project on screen, at its own
 * address or an item's under it, is the current page's. An <a> itself, its repos and environments
 * link through spans (F91, F93), and its ticket ids are plain text, so that a tap on the tab never
 * opens the tracker. Under the mouse or a finger it reads what its project's screen shows first
 * (`screen-reads.ts`).
 */

import { Link } from '@tanstack/react-router';
import { StatusIcon } from '@/components/projects/status-icon';
import { LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { useProjectOnScreen } from '@/hooks/use-project-address';
import type { ProjectTab as Project } from '@/hooks/use-projects';
import { projectStatusLine } from '@/lib/utils/status-labels';
import { cn } from '@/lib/utils';

export function ProjectTab({ project, archived = false }: { project: Project; archived?: boolean }) {
  const status = projectStatusLine(project);
  // The tab of the project on screen is no switch (F1.6): it goes to the project's own address.
  const onScreen = useProjectOnScreen() === project.id;
  return (
    <Link
      to="/projects/$address"
      params={{ address: project.address }}
      state={onScreen ? undefined : { fromList: project.id }}
      preload="intent"
      className={cn('tab', project.state === 'finished' && 'finished')}
      data-testid="projects.tab"
    >
      <div className="tab-name">
        <span data-testid="projects.tab.name">
          <LinkedText text={project.name ?? 'New project'} nested tickets={false} />
        </span>
        {project.ticket && (
          <span className="card-id mono" data-testid="projects.tab.ticket">
            {project.ticket}
          </span>
        )}
      </div>
      <div className="tab-status" data-testid="projects.tab.status">
        <StatusIcon project={project} archived={archived} />
        <span className="tab-step" title={status.text} data-testid="projects.tab.step">
          <LinkedText text={status.text} nested tickets={false} />
          {status.at && (
            <>
              {' '}
              <Time at={status.at} />
            </>
          )}
        </span>
        {project.badge.count > 0 && (
          <span
            className={cn('count-badge', project.badge.urgent && 'urgent')}
            title={`${project.badge.count} waiting on you`}
            data-testid="projects.tab.badge"
            data-urgent={project.badge.urgent}
          >
            {project.badge.count}
          </span>
        )}
      </div>
    </Link>
  );
}

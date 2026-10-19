/**
 * A project's tab (F1.1, F1.2): its name, its ticket id and its status line, opening the project
 * at its own address. The tab of the project on screen is the current page's. An <a> itself, its
 * text links through spans (F91, F93).
 */

import { Link } from '@tanstack/react-router';
import { LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import type { ProjectTab as Project } from '@/hooks/use-projects';
import { projectStatusLine } from '@/lib/utils/status-labels';
import { cn } from '@/lib/utils';

export function ProjectTab({ project }: { project: Project }) {
  const status = projectStatusLine(project);
  return (
    <Link
      to="/projects/$projectId"
      params={{ projectId: project.id }}
      activeOptions={{ exact: true }}
      className={cn('tab', project.state === 'finished' && 'finished')}
      data-testid="projects.tab"
    >
      <div className="tab-name">
        <span data-testid="projects.tab.name">
          <LinkedText text={project.name ?? 'New project'} nested />
        </span>
        {project.ticket && (
          <span className="card-id mono" data-testid="projects.tab.ticket">
            <LinkedText text={project.ticket} nested />
          </span>
        )}
      </div>
      <div className="tab-status" data-testid="projects.tab.status">
        <span>
          <LinkedText text={status.text} nested />
          {status.more && ', …'}
          {status.at && (
            <>
              {' '}
              <Time at={status.at} />
            </>
          )}
        </span>
      </div>
    </Link>
  );
}

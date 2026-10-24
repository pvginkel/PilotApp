/**
 * A project's tab (F1.1, F1.2): its name, its ticket id and its status line, opening the project
 * at its own address; its status icon, the pause (F1.3, F141); and the badge counting the items
 * waiting on the person, orange when one of them is urgent (F1.4). The tab of the project on
 * screen, at its own address or an item's under it, is the current page's. An <a> itself, its
 * text links through spans (F91, F93).
 */

import { Link } from '@tanstack/react-router';
import { StatusIcon } from '@/components/projects/status-icon';
import { LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import type { ProjectTab as Project } from '@/hooks/use-projects';
import { projectStatusLine } from '@/lib/utils/status-labels';
import { cn } from '@/lib/utils';

export function ProjectTab({ project, archived = false }: { project: Project; archived?: boolean }) {
  const status = projectStatusLine(project);
  return (
    <Link
      to="/projects/$projectId"
      params={{ projectId: project.id }}
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
        <StatusIcon project={project} archived={archived} />
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

/**
 * The project list and the archived projects, as GET /api/projects reads them. Both refetch when
 * the window comes back into focus, and after the person's own writes, which invalidate every
 * query; nothing pushes them (F1).
 */

import { useGetProjects } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

export type ProjectTab = components['schemas']['ProjectListResponseSchema.e86ccd6.ProjectTabSchema'];

function useProjects(archived: boolean, scope: string) {
  const query = useGetProjects({ query: { archived } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation(scope, { isLoading: query.isLoading, error: query.error });
  return query;
}

export function useProjectList() {
  return useProjects(false, 'projects.list');
}

export function useArchivedProjects() {
  return useProjects(true, 'projects.archived');
}

interface Groups {
  /** The person's projects, under the list's head. */
  mine: ProjectTab[];
  others: ProjectTab[];
  finished: ProjectTab[];
}

/** The list's groups (F1.5, F1.7): finished projects under Finished, member or not. */
export function groupProjects(projects: ProjectTab[]): Groups {
  const active = projects.filter((project) => project.state !== 'finished');
  return {
    mine: active.filter((project) => project.member),
    others: active.filter((project) => !project.member),
    finished: projects.filter((project) => project.state === 'finished'),
  };
}

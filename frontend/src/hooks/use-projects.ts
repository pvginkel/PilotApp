/**
 * The project list and the archived projects, as GET /api/projects reads them, and a project's
 * head, as GET /api/projects/<id> does. Each refetches when the window comes back into focus,
 * after the person's own writes, which invalidate every query, and on a project's live event
 * (F1, F2, F80.2; use-project-events.ts).
 */

import { useGetProjects, useGetProjectsByProjectId } from '@/lib/api/generated/hooks';
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

export type ProjectHead = components['schemas']['ProjectHeadSchema.e86ccd6'];

export function useProjectHead(id: string) {
  const query = useGetProjectsByProjectId({ path: { project_id: id } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('project.head', { isLoading: query.isLoading, error: query.error });
  return query;
}

/**
 * Whether the project is archived, from the head the page already reads (useProjectHead), its
 * cache shared and not read again on mount; false until it is read.
 */
export function useArchived(id: string): boolean {
  return useGetProjectsByProjectId({ path: { project_id: id } }, { refetchOnMount: false }).data?.archived ?? false;
}

/** Whether the project's auto pilot is off, from the head as useArchived reads it; false until it is read. */
export function useAutopilotOff(id: string): boolean {
  return useGetProjectsByProjectId({ path: { project_id: id } }, { refetchOnMount: false }).data?.autopilot === false;
}

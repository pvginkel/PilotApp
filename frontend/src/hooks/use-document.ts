/**
 * The documents the overlay reads on its own. An item's, as GET /api/items/<id>/document reads it
 * (F28): its timeline entry and its project, with its text as Done fixed it where Done did
 * (F13.3). The project's handbook (F129.4) and its project document, `project.md` (F37.4), as
 * GET /api/projects/<id>/handbook and …/draft read them, as last published. Each refetches when
 * the window comes back into focus, after the person's own writes, which invalidate every query,
 * and on its project's live event (F80.2; use-project-events.ts).
 */

import { useGetItemsDocumentByItemId, useGetProjectsDraftByProjectId, useGetProjectsHandbookByProjectId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

export type ItemDocument = components['schemas']['ItemDocumentSchema.1fdd8ae'];
export type ProjectDocument = components['schemas']['ProjectDocumentSchema.1fdd8ae'];

export function useItemDocument(id: string) {
  const query = useGetItemsDocumentByItemId({ path: { item_id: id } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('overlay.document', { isLoading: query.isLoading, error: query.error });
  return query;
}

export function useHandbook(projectId: string) {
  const query = useGetProjectsHandbookByProjectId({ path: { project_id: projectId } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('overlay.handbook', { isLoading: query.isLoading, error: query.error });
  return query;
}

export function useProjectDraft(projectId: string) {
  const query = useGetProjectsDraftByProjectId({ path: { project_id: projectId } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('overlay.draft', { isLoading: query.isLoading, error: query.error });
  return query;
}

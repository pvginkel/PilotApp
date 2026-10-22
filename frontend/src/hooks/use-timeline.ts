/**
 * A project's timeline, as GET /api/projects/<id>/timeline reads it whole (F8). It refetches when
 * the window comes back into focus, after the person's own writes, which invalidate every query,
 * and on its project's live event (F80.2; use-project-events.ts).
 */

import { useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

type Schemas = components['schemas'];
export type TimelineItem = Schemas['TimelineSchema.1fdd8ae.TimelineItemSchema'];
export type TimelineUser = Schemas['TimelineSchema.1fdd8ae.UserSchema'];
export type Block = Schemas['TimelineSchema.1fdd8ae.BlockSchema'];
export type BodyPart = NonNullable<TimelineItem['body']>[number];
export type ProsePart = Schemas['TimelineSchema.1fdd8ae.ProsePartSchema'];

export function useTimeline(id: string) {
  const query = useGetProjectsTimelineByProjectId({ path: { project_id: id } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('project.timeline', { isLoading: query.isLoading, error: query.error });
  return query;
}

/** A prose item's blocks, in their order. */
export function blocksOf(item: TimelineItem): Block[] {
  return (item.body ?? []).flatMap((part) => (part.type === 'block' ? [part.block] : []));
}

/** The line's title: a registered document's file name while its text gives none (F35). */
export function titleOf(item: TimelineItem): string {
  // The API gives a file name wherever it gives no title.
  return item.title ?? item.file_name!;
}

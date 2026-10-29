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
export type Attachment = Schemas['TimelineSchema.1fdd8ae.AttachmentSchema'];
type ProsePart = Schemas['TimelineSchema.1fdd8ae.ProsePartSchema'];
type Timeline = Schemas['TimelineSchema.1fdd8ae'];

export function useTimeline(id: string) {
  const query = useGetProjectsTimelineByProjectId({ path: { project_id: id } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('project.timeline', { isLoading: query.isLoading, error: query.error });
  return query;
}

/** An item of a project's timeline, from the timeline's read, once read; none for no id. */
export function useTimelineItem(projectId: string, itemId: string | undefined): TimelineItem | undefined {
  const { data } = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  return itemId === undefined ? undefined : data?.items.find((item) => item.id === itemId);
}

export const isProse = (part: BodyPart): part is ProsePart => part.type === 'prose';

/** A prose item's blocks, in their order. */
export function blocksOf(item: TimelineItem): Block[] {
  return (item.body ?? []).flatMap((part) => (part.type === 'block' ? [part.block] : []));
}

/** An item's attachment by its id. */
export const attachmentIn = (item: TimelineItem, id: string): Attachment | undefined =>
  item.attachments.find((attachment) => attachment.id === id);

/** An attachment where it hangs: on its item, or on none, a draft's material until Create project (F36.6). */
interface Hung {
  item: TimelineItem | null;
  attachment: Attachment;
}

/** Every attachment of the timeline's read, where it hangs. */
function hungIn(timeline: Timeline): Hung[] {
  return [
    ...timeline.items.flatMap((item) => item.attachments.map((attachment) => ({ item, attachment }))),
    ...timeline.unhung_attachments.map((attachment) => ({ item: null, attachment })),
  ];
}

/** An attachment of the timeline's read by its id. */
export const hungById = (timeline: Timeline, id: string): Hung | undefined => hungIn(timeline).find(({ attachment }) => attachment.id === id);

/** An attachment of the timeline's read by its path in the project's folder, `attachments/<batch>/<filename>`. */
export function hungAt(timeline: Timeline, path: string): Hung | undefined {
  const [root, batch, ...filename] = path.split('/');
  if (root !== 'attachments') return undefined;
  return hungIn(timeline).find(({ attachment }) => attachment.batch === Number(batch) && attachment.filename === filename.join('/'));
}

/**
 * Whether the record counts the block answered: an answer, a deferral included, or an action's Done;
 * never an action Pilot claimed and has not done, which stays open (F21.6; DB 154).
 */
export const isAnswered = (block: Block) => block.claim === null && (block.answer !== null || block.done !== null);

/** The line's title: a registered document's file name while its text gives none (F35). */
export function titleOf(item: TimelineItem): string {
  // The API gives a file name wherever it gives no title.
  return item.title ?? item.file_name!;
}

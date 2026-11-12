/**
 * A project's timeline, as GET /api/projects/<id>/timeline reads it whole (F8). It refetches when
 * the window comes back into focus, after the person's own writes, which invalidate every query,
 * and on its project's live event (F80.2; use-project-events.ts).
 */

import { RESUMABLE } from '@/hooks/use-work-acts';
import { useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

type Schemas = components['schemas'];
export type TimelineItem = Schemas['TimelineSchema.1fdd8ae.TimelineItemSchema'];
export type TimelineUser = Schemas['TimelineSchema.1fdd8ae.UserSchema'];
export type Block = Schemas['TimelineSchema.1fdd8ae.BlockSchema'];
export type BodyPart = NonNullable<TimelineItem['body']>[number];
export type Attachment = Schemas['TimelineSchema.1fdd8ae.AttachmentSchema'];
/** What Pilot does on an item that is Pilot's (F13.7). */
export type PilotsWork = Schemas['TimelineSchema.1fdd8ae.PilotsWorkSchema'];
type ProsePart = Schemas['TimelineSchema.1fdd8ae.ProsePartSchema'];
type Timeline = Schemas['TimelineSchema.1fdd8ae'];

export function useTimeline(id: string) {
  const query = useGetProjectsTimelineByProjectId({ path: { project_id: id } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('project.timeline', { isLoading: query.isLoading, error: query.error });
  return query;
}

/**
 * An item of a project's timeline, from the timeline's read: none for no id or until read; null
 * where the read has no such item, or failed.
 */
export function useTimelineItem(projectId: string, itemId: string | undefined): TimelineItem | null | undefined {
  const { data, error } = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  if (itemId === undefined || (data === undefined && error === null)) return undefined;
  return data?.items.find((item) => item.id === itemId) ?? null;
}

export const isProse = (part: BodyPart): part is ProsePart => part.type === 'prose';

/**
 * Whether an entry of the read is a line of the timeline: every one but Pilot's jobs, each of which
 * shows on the item it follows from, the setup aside (F59.1). A job keeps its entry, where its
 * session log finds it.
 */
export const isLine = (item: TimelineItem) => item.work === null || !item.work.pilots_own || item.work.setup;

/**
 * Whether an item can be acted on, which "N open above" counts (F11): open, and a prose item but
 * the opening that is not Pilot's, a notice urgent or not, whichever member it is for; or a work
 * item stopped or failed, until it is retried, and not while its nudge is owed. Never work that
 * runs, starts or is held, nor a wait. It is what waits on a person (F94.5) less two of its
 * filters, a notice's urgency and the member an item is for.
 */
export function isActionable(item: TimelineItem): boolean {
  if (item.done !== null) return false;
  switch (item.form) {
    case 'prose':
      return item.kind !== 'opening' && item.pilots_work === null;
    case 'work':
      // The API gives every work item its session.
      return RESUMABLE.includes(item.work!.state) && item.work!.retried === null && !item.work!.nudge_owed;
    case 'wait':
      return false;
    default: {
      const unhandled: never = item.form;
      return unhandled;
    }
  }
}

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

/** The folder of the project's attached material in its folder (F74). */
const ATTACHMENTS = 'attachments';

/** An attachment of the timeline's read by its path in the project's folder, `attachments/<batch>/<filename>`. */
export function hungAt(timeline: Timeline, path: string): Hung | undefined {
  const [root, batch, ...filename] = path.split('/');
  if (root !== ATTACHMENTS) return undefined;
  return hungIn(timeline).find(({ attachment }) => attachment.batch === Number(batch) && attachment.filename === filename.join('/'));
}

/** The path a link names in the project's folder: as written, less a leading `./`, its escapes decoded. */
export function pathOfLink(href: string): string {
  const path = href.replace(/^\.\//, '');
  try {
    return decodeURI(path);
  } catch {
    // An escape of no UTF-8: the path as written, which names no file.
    return path;
  }
}

/** Whether a link names a path in the project's attached material, `attachments/…`. */
export const linksMaterial = (href: string) => pathOfLink(href).startsWith(`${ATTACHMENTS}/`);

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

/**
 * The badges of a project's running work kept current (F156.8, F156.12). The page computes none of
 * an estimate: a work item's rides its timeline item and each `work_moved`, the head's the head's
 * read. While a badge shows, GET /api/projects/<id>/estimates is read each minute, by the wall
 * clock (use-now.ts), and written over both as read: the head's, and each work item's, none for a
 * work item the read does not list. A move that changes a work item's badge, or the mark its
 * sentence turns on, reads it at once, so that the head's follows. What changed while a read was
 * under way, a move's or a read's of its own, is left as it stands.
 */

import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { wallClock } from '@/hooks/use-now';
import type { ProjectHead } from '@/hooks/use-projects';
import type { TimelineItem } from '@/hooks/use-timeline';
import { api } from '@/lib/api/generated/client';
import { useGetProjectsByProjectId, useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { patchQueryData } from '@/lib/patch-query';

type Timeline = components['schemas']['TimelineSchema.1fdd8ae'];
type Work = NonNullable<TimelineItem['work']>;

const MINUTE = 60_000;
/** How often the wall clock is looked at for the minute, in milliseconds. */
const TICK = 5_000;

/**
 * What the work items' badges show, to compare, the mark their sentence turns on among it: nothing
 * of how long a run has taken, which every read moves.
 */
function badgesOf(timeline: Timeline): string {
  return timeline.items
    .flatMap(({ id, work }) => {
      const estimate = work?.estimate ?? null;
      return estimate === null
        ? []
        : [[id, estimate.minutes, estimate.longer_than_usual, estimate.marked, estimate.kind].join(' ')];
    })
    .join('\n');
}

function withEstimate(item: TimelineItem, work: Work, estimate: Work['estimate']): TimelineItem {
  return work.estimate === null && estimate === null ? item : { ...item, work: { ...work, estimate } };
}

export function useEstimates(projectId: string): void {
  const queryClient = useQueryClient();
  const params = useMemo(() => ({ path: { project_id: projectId } }), [projectId]);
  const head = useGetProjectsByProjectId(params, { refetchOnMount: false }).data;
  const timeline = useGetProjectsTimelineByProjectId(params, { refetchOnMount: false }).data;
  const badges = timeline === undefined ? undefined : badgesOf(timeline);
  const shows = (head !== undefined && head.estimate !== null) || (badges !== undefined && badges !== '');
  // When the estimates were last read, by the wall clock, and the badges that read wrote.
  const readAt = useRef(0);
  const known = useRef<string | undefined>(undefined);

  const read = useCallback(async () => {
    readAt.current = wallClock();
    const headKey = ['getProjectsByProjectId', params];
    const timelineKey = ['getProjectsTimelineByProjectId', params];
    const sentHead = queryClient.getQueryData<ProjectHead>(headKey);
    const sentWork = new Map(queryClient.getQueryData<Timeline>(timelineKey)?.items.map(({ id, work }) => [id, work]));
    // A read that fails or is refused is left: the next minute reads again.
    const answer = await api.GET('/api/projects/{project_id}/estimates', { params }).catch(() => undefined);
    const estimates = answer?.data;
    if (estimates === undefined) return;
    const listed = new Map(estimates.work_items.map(({ id, estimate }) => [id, estimate]));
    patchQueryData<ProjectHead>(queryClient, headKey, (now) =>
      now === undefined || now !== sentHead ? now : { ...now, estimate: estimates.estimate },
    );
    patchQueryData<Timeline>(queryClient, timelineKey, (now) =>
      now === undefined
        ? undefined
        : {
            ...now,
            items: now.items.map((item) =>
              item.work === null || item.work !== sentWork.get(item.id) ? item : withEstimate(item, item.work, listed.get(item.id) ?? null),
            ),
          },
    );
    const written = queryClient.getQueryData<Timeline>(timelineKey);
    if (written !== undefined) known.current = badgesOf(written);
  }, [params, queryClient]);

  useEffect(() => {
    if (badges === undefined) return;
    const moved = known.current !== undefined && known.current !== badges;
    known.current = badges;
    if (moved) void read();
  }, [badges, read]);

  useEffect(() => {
    if (!shows) return undefined;
    // What shows was read, or moved, just now.
    readAt.current = wallClock();
    const timer = setInterval(() => {
      if (wallClock() - readAt.current >= MINUTE) void read();
    }, TICK);
    return () => clearInterval(timer);
  }, [shows, read]);
}

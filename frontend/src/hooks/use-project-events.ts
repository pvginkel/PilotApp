/**
 * The screens kept live (F80.2). The server's `project_changed` names a project whose timeline,
 * head or tab moved, and what the screens show of it is read again: its timeline, its head, a
 * document of it in the overlay, its handbook and its project document, and the project lists'
 * tabs; a handbook's save sends none, and the project document's one only where it renames the
 * project. An event reaches only the browsers whose stream the sending process holds, so each
 * time the stream comes up everything they show is read again (design 2 §6.2). Nothing waits for
 * the stream: the screens are read without it (SSE-4).
 *
 * The server's `work_moved` carries a work item's session as it moves (F26.2, F80.2): it replaces
 * the item's in its project's timeline as read, with no read of its own, and so in the session log
 * over it. A read of the timeline under way when one arrives may have been made before it, so the
 * moves heard meanwhile go over that read once it lands.
 */

import { useEffect } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useSseContext } from '@/contexts/sse-context';
import type { ItemDocument } from '@/hooks/use-document';
import type { components } from '@/lib/api/generated/types';

type Timeline = components['schemas']['TimelineSchema.1fdd8ae'];
type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];

/** The server's event, `{"project_id": <id>}`. */
const EVENT = 'project_changed';
/** The server's event, `{"project_id": <id>, "item_id": <id>, "work": <the item's work>}`. */
const WORK_EVENT = 'work_moved';

interface ProjectChanged {
  project_id: string;
}

interface WorkMoved {
  project_id: string;
  item_id: string;
  work: Work;
}

const LISTS = ['getProjects'] as const;
const HEAD = 'getProjectsByProjectId';
const TIMELINE = 'getProjectsTimelineByProjectId';
const DOCUMENT = 'getItemsDocumentByItemId';
const HANDBOOK = 'getProjectsHandbookByProjectId';
const DRAFT = 'getProjectsDraftByProjectId';

function readAgain(queryClient: QueryClient, projects: ReadonlySet<string>): void {
  void queryClient.invalidateQueries({ queryKey: LISTS });
  for (const project_id of projects) {
    for (const key of [HEAD, TIMELINE, HANDBOOK, DRAFT]) {
      void queryClient.invalidateQueries({ queryKey: [key, { path: { project_id } }] });
    }
  }
  // A document's read is keyed by its item; what it read names its project.
  void queryClient.invalidateQueries({
    queryKey: [DOCUMENT],
    predicate: (query) => {
      const read = query.state.data as ItemDocument | undefined;
      return read !== undefined && projects.has(read.project_id);
    },
  });
}

const timelineOf = (project_id: string) => [TIMELINE, { path: { project_id } }];

function moveWork(queryClient: QueryClient, project: string, item: string, work: Work): void {
  queryClient.setQueryData<Timeline>(timelineOf(project), (timeline) =>
    timeline === undefined ? undefined : { ...timeline, items: timeline.items.map((each) => (each.id === item ? { ...each, work } : each)) },
  );
}

export function useProjectEvents(): void {
  const queryClient = useQueryClient();
  const { isConnected, addEventListener } = useSseContext();

  useEffect(() => {
    // Events that arrive together are read again once, after them: without OIDC every
    // connection hears each event once per person.
    const pending = new Set<string>();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = addEventListener(EVENT, (data) => {
      pending.add((data as ProjectChanged).project_id);
      timer ??= setTimeout(() => {
        timer = undefined;
        readAgain(queryClient, new Set(pending));
        pending.clear();
      });
    });
    return () => {
      unsubscribe();
      clearTimeout(timer);
    };
  }, [addEventListener, queryClient]);

  useEffect(() => {
    // The moves heard while a project's timeline is being read, by project, then by item.
    const heard = new Map<string, Map<string, Work>>();
    const unsubscribe = addEventListener(WORK_EVENT, (data) => {
      const { project_id, item_id, work } = data as WorkMoved;
      moveWork(queryClient, project_id, item_id, work);
      if (queryClient.isFetching({ queryKey: timelineOf(project_id), exact: true }) === 0) return;
      const moves = heard.get(project_id) ?? new Map<string, Work>();
      moves.set(item_id, work);
      heard.set(project_id, moves);
    });
    const unwatch = queryClient.getQueryCache().subscribe((event) => {
      if (event.type !== 'updated' || event.query.queryKey[0] !== TIMELINE) return;
      const project = (event.query.queryKey[1] as { path: { project_id: string } }).path.project_id;
      const { action } = event;
      // A read that starts is made after every move heard so far; one that lands may be older
      // than the moves heard while it was under way. A write of the cache's own is no read.
      if (action.type === 'fetch' || action.type === 'error') heard.delete(project);
      if (action.type !== 'success' || action.manual === true) return;
      const moves = heard.get(project);
      heard.delete(project);
      moves?.forEach((work, item) => moveWork(queryClient, project, item, work));
    });
    return () => {
      unsubscribe();
      unwatch();
    };
  }, [addEventListener, queryClient]);

  useEffect(() => {
    if (!isConnected) return;
    void queryClient.invalidateQueries({ queryKey: LISTS });
    void queryClient.invalidateQueries({ queryKey: [HEAD] });
    void queryClient.invalidateQueries({ queryKey: [TIMELINE] });
    for (const key of [DOCUMENT, HANDBOOK, DRAFT]) void queryClient.invalidateQueries({ queryKey: [key] });
  }, [isConnected, queryClient]);
}

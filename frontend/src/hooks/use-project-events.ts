/**
 * The screens kept live (F80.2). The server's `project_changed` names a project whose timeline,
 * head or tab moved, and what the screens show of it is read again: its timeline, its head, a
 * document of it in the overlay, its handbook and its project document, its chats, and the project
 * lists' tabs. A chat's open and close, and each move of its session's state, send one: the Chat
 * tab shows a chat that opens, its close, and whether Pilot is answering (F40.3). A save of any of
 * the project's documents, the handbook and the project document included, sends one where it
 * changes the text or makes its turn the document's writer, and a turn's end sends one for each
 * document it lets go: Pilot's dots come and go live (F35). An event reaches only the browsers
 * whose stream the sending process holds, so each time the stream comes up everything they show is
 * read again (design 2 §6.2). Nothing waits for the stream: the screens are read without it
 * (SSE-4). A read under way when the event arrives is left to land, and read again once it has.
 * An event a page's write committed names that page, which reads nothing on it: the write's own
 * hook reads every query again once it is answered, so a click reads each query once.
 *
 * The server's `work_moved` carries a work item's session as it moves (F26.2, F80.2): it replaces
 * the item's in its project's timeline as read, with no read of its own, and so in the session log
 * over it; a job's goes too where an item shows it, as its job or as the job after its turn
 * (F59.1). A read of the timeline under way when one arrives may have been made before it, so the
 * moves heard meanwhile go over that read once it lands.
 */

import { useEffect } from 'react';
import { useQueryClient, type Query, type QueryClient, type QueryFilters } from '@tanstack/react-query';
import { useSseContext } from '@/contexts/sse-context';
import type { ItemDocument } from '@/hooks/use-document';
import { SENDER } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';

type Timeline = components['schemas']['TimelineSchema.1fdd8ae'];
type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];
type Job = components['schemas']['TimelineSchema.1fdd8ae.JobSchema'];

/** The server's event, `{"project_id": <id>}`, with `"sender": <page>` where a page's write committed it. */
const EVENT = 'project_changed';
/** The server's event, `{"project_id": <id>, "item_id": <id>, "work": <the item's work>}`. */
const WORK_EVENT = 'work_moved';

interface ProjectChanged {
  project_id: string;
  sender?: string;
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
const CHATS = 'getProjectsChatsByProjectId';

/**
 * Reads again the queries `read` is handed, never over a read under way: a query whose read is under
 * way is read again once that read lands. A read made over one cancels it, so events closer together
 * than a read takes would keep every read from landing, and an `await` on the query's invalidation,
 * as Create project's, from ending. A read under way may predate the event, and is not taken for it.
 */
function reader(queryClient: QueryClient): { read: (filters: QueryFilters) => void; stop: () => void } {
  const cache = queryClient.getQueryCache();
  const owed = new Set<Query>();
  const readOne = (query: Query) => {
    if (query.state.fetchStatus === 'idle') void queryClient.invalidateQueries({ queryKey: query.queryKey, exact: true });
    else owed.add(query);
  };
  const unwatch = cache.subscribe((event) => {
    if (event.type === 'removed') owed.delete(event.query);
    if (event.type !== 'updated' || event.query.state.fetchStatus !== 'idle' || !owed.delete(event.query)) return;
    // Once every listener has heard the read land: the moves heard over it go onto it first.
    const { query } = event;
    queueMicrotask(() => readOne(query));
  });
  return {
    read: (filters) => cache.findAll(filters).forEach(readOne),
    stop: () => {
      unwatch();
      owed.clear();
    },
  };
}

function readAgain(read: (filters: QueryFilters) => void, projects: ReadonlySet<string>): void {
  read({ queryKey: LISTS });
  for (const project_id of projects) {
    for (const key of [HEAD, TIMELINE, HANDBOOK, DRAFT, CHATS]) {
      read({ queryKey: [key, { path: { project_id } }] });
    }
  }
  // A document's read is keyed by its item; what it read names its project.
  read({
    queryKey: [DOCUMENT],
    predicate: (query) => {
      const shown = query.state.data as ItemDocument | undefined;
      return shown !== undefined && projects.has(shown.project_id);
    },
  });
}

const timelineOf = (project_id: string) => [TIMELINE, { path: { project_id } }];

/**
 * Writes `work` into the item's in its project's timeline as read, and into each item's job and job
 * after its turn that is the item; given `from`, only where the session there is still in one of
 * those states, so that a move heard first is not undone.
 */
export function moveWork(queryClient: QueryClient, project: string, item: string, work: Work, from?: readonly Work['state'][]): void {
  const moves = (current: Work | null) => from === undefined || (current !== null && from.includes(current.state));
  const moveJob = (job: Job | null) => (job !== null && job.id === item && moves(job.work) ? { ...job, work } : job);
  queryClient.setQueryData<Timeline>(timelineOf(project), (timeline) =>
    timeline === undefined
      ? undefined
      : {
          ...timeline,
          items: timeline.items.map((each) => {
            const job = moveJob(each.job);
            const afterTurn = moveJob(each.after_turn);
            const moved = each.id === item && moves(each.work) ? { ...each, work } : each;
            return job === each.job && afterTurn === each.after_turn ? moved : { ...moved, job, after_turn: afterTurn };
          }),
        },
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
    const { read, stop } = reader(queryClient);
    const unsubscribe = addEventListener(EVENT, (data) => {
      const { project_id, sender } = data as ProjectChanged;
      if (sender === SENDER) return;
      pending.add(project_id);
      timer ??= setTimeout(() => {
        timer = undefined;
        readAgain(read, new Set(pending));
        pending.clear();
      });
    });
    return () => {
      unsubscribe();
      clearTimeout(timer);
      stop();
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
    for (const key of [DOCUMENT, HANDBOOK, DRAFT, CHATS]) void queryClient.invalidateQueries({ queryKey: [key] });
  }, [isConnected, queryClient]);
}

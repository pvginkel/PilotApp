/**
 * The screens kept live (F80.2). The server's `project_changed` names a project whose timeline,
 * head or tab moved, and what the screens show of it is read again: its timeline, its head, a
 * document of it in the overlay, its handbook and its project document, and the project lists'
 * tabs; a handbook's save sends none, and the project document's one only where it renames the
 * project. An event reaches only the browsers whose stream the sending process holds, so each
 * time the stream comes up everything they show is read again (design 2 §6.2). Nothing waits for
 * the stream: the screens are read without it (SSE-4).
 */

import { useEffect } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useSseContext } from '@/contexts/sse-context';
import type { ItemDocument } from '@/hooks/use-document';

/** The server's event, `{"project_id": <id>}`. */
const EVENT = 'project_changed';

interface ProjectChanged {
  project_id: string;
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
    if (!isConnected) return;
    void queryClient.invalidateQueries({ queryKey: LISTS });
    void queryClient.invalidateQueries({ queryKey: [HEAD] });
    void queryClient.invalidateQueries({ queryKey: [TIMELINE] });
    for (const key of [DOCUMENT, HANDBOOK, DRAFT]) void queryClient.invalidateQueries({ queryKey: [key] });
  }, [isConnected, queryClient]);
}

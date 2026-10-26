/**
 * A project's chats as the Chat tab reads them (F40.3): the definition chat first where one exists,
 * then the project's chats in the order they opened, each open or closed, and whether Pilot is
 * answering in it; read again when the window regains the focus and on `project_changed`
 * (use-project-events.ts). `pending` while the read has nothing yet, `failed` while its latest
 * attempt failed, whatever an earlier one read (F113).
 *
 * The composer's writes (F38, F44): a person's message, and the Stop of Pilot's answer, by any
 * person whoever sent the message. Each answer says at once whether Pilot answers in its chat, into
 * the list as read; then every screen reads again. A refusal is the query client's toast, the API's
 * words. Their form events are `chat.send`'s and `chat.stop`'s.
 *
 * The unread dot (F43): the list says whether a reply of Pilot's came after the person last saw the
 * chat to its end, on any device, and the dot stands on the head's Discuss and the Chat tab while it
 * does and this page does not show the chat at its end. Shown there, in a page in view, the chat is
 * marked seen, its answer into the list as read: a reply watched arriving leaves no dot. No other browser hears of
 * the mark; each drops its dot at its next read of the list. Its form events are `chat.read`'s.
 */

import { useEffect, useRef, useSyncExternalStore } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import {
  useGetProjectsChatsByProjectId,
  usePostProjectsChatMessagesByProjectId,
  usePostProjectsChatStopByProjectId,
  usePutProjectsChatReadByProjectId,
} from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

type ChatList = components['schemas']['ChatListSchema.f9d9b43'];
export type Chat = ChatList['chats'][number];
type TurnState = components['schemas']['ChatTurnSchema.f9d9b43']['state'];

type ChatRead = ChatList | 'pending' | 'failed';

/** The states of a chat's session a message leaves it in while Pilot answers: the Stop's. */
const ANSWERING: readonly TurnState[] = ['held', 'starting', 'running'];

const chatsOf = (projectId: string) => ['getProjectsChatsByProjectId', { path: { project_id: projectId } }];

export function useProjectChats(projectId: string): ChatRead {
  const query = useGetProjectsChatsByProjectId({ path: { project_id: projectId } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('panel.chat', { isLoading: query.isLoading, error: query.error });
  if (query.error !== null) return 'failed';
  return query.data ?? 'pending';
}

/** Whether Pilot answers in the chat, into the project's list as read; a chat it does not hold yet comes with its next read. */
function setAnswering(queryClient: QueryClient, projectId: string, chatId: string, answering: boolean): void {
  queryClient.setQueryData<ChatList>(chatsOf(projectId), (list) =>
    list === undefined ? undefined : { ...list, chats: list.chats.map((chat) => (chat.id === chatId ? { ...chat, answering } : chat)) },
  );
}

/** The signed-in person's message to the project's chat, the words verbatim; answers whether the server took it. */
export function useSendMessage(projectId: string) {
  const queryClient = useQueryClient();
  const mutation = usePostProjectsChatMessagesByProjectId();
  const fields = { project: projectId };
  const act = (words: string): Promise<boolean> => {
    trackFormSubmit('chat.send', fields);
    return mutation.mutateAsync({ path: { project_id: projectId }, body: { words } }).then(
      (turn) => {
        trackFormSuccess('chat.send', fields);
        setAnswering(queryClient, projectId, turn.chat, ANSWERING.includes(turn.state));
        return true;
      },
      () => {
        trackFormError('chat.send', fields);
        return false;
      },
    );
  };
  return { act, pending: mutation.isPending };
}

/** The signed-in person's Stop of Pilot's answer in the project's open chat (F44). */
export function useStopChat(projectId: string) {
  const queryClient = useQueryClient();
  const mutation = usePostProjectsChatStopByProjectId();
  const fields = { project: projectId };
  const act = (): Promise<void> => {
    trackFormSubmit('chat.stop', fields);
    return mutation.mutateAsync({ path: { project_id: projectId } }).then(
      (chat) => {
        trackFormSuccess('chat.stop', fields);
        setAnswering(queryClient, projectId, chat.id, chat.answering);
      },
      () => trackFormError('chat.stop', fields),
    );
  };
  return { act, pending: mutation.isPending };
}

/** The projects whose chat this page shows at its end now. */
const atEnd = new Set<string>();
const atEndListeners = new Set<() => void>();

function subscribeAtEnd(listener: () => void): () => void {
  atEndListeners.add(listener);
  return () => atEndListeners.delete(listener);
}

function subscribeVisibility(listener: () => void): () => void {
  document.addEventListener('visibilitychange', listener);
  return () => document.removeEventListener('visibilitychange', listener);
}

function setAtEnd(projectId: string, shown: boolean): void {
  if (shown) atEnd.add(projectId);
  else atEnd.delete(projectId);
  atEndListeners.forEach((listener) => listener());
}

/** Whether the unread dot stands on the project's Discuss and Chat tab. */
export function useChatDot(projectId: string): boolean {
  const { data } = useGetProjectsChatsByProjectId({ path: { project_id: projectId } }, { refetchOnWindowFocus: 'always' });
  const shown = useSyncExternalStore(subscribeAtEnd, () => atEnd.has(projectId));
  return data?.unread === true && !shown;
}

/**
 * The project's chat, which this page shows at its end while `atEnd`, marked seen there while the
 * page is in view whenever the list says a reply is unread; a mark that failed is made again once
 * the chat is shown again.
 */
export function useChatSeen(projectId: string, atEnd: boolean, unread: boolean): void {
  const queryClient = useQueryClient();
  const visible = useSyncExternalStore(subscribeVisibility, () => document.visibilityState === 'visible');
  const shown = atEnd && visible;
  const { mutateAsync, isPending } = usePutProjectsChatReadByProjectId();
  const tried = useRef(false);
  useEffect(() => {
    if (!shown) return undefined;
    setAtEnd(projectId, true);
    return () => setAtEnd(projectId, false);
  }, [projectId, shown]);
  useEffect(() => {
    if (!shown || !unread) {
      tried.current = false;
      return;
    }
    if (tried.current || isPending) return;
    tried.current = true;
    const fields = { project: projectId };
    trackFormSubmit('chat.read', fields);
    mutateAsync({ path: { project_id: projectId } }).then(
      (place) => {
        trackFormSuccess('chat.read', fields);
        tried.current = false;
        queryClient.setQueryData<ChatList>(chatsOf(projectId), (list) => (list === undefined ? undefined : { ...list, ...place }));
      },
      () => trackFormError('chat.read', fields),
    );
  }, [projectId, shown, unread, isPending, mutateAsync, queryClient]);
}

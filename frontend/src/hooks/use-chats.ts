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
 */

import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import {
  useGetProjectsChatsByProjectId,
  usePostProjectsChatMessagesByProjectId,
  usePostProjectsChatStopByProjectId,
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

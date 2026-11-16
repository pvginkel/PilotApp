/**
 * A project's conversations as the Conversations tab reads them (F150.12): the calling sessions'
 * conversations with Pilot about the project, whoever opened them, in the order they opened, each
 * with the environment and the session that opened it, open or closed, and whether Pilot is
 * answering in it; read again when the window regains the focus and on `project_changed`
 * (use-project-events.ts). `pending` while the read has nothing yet, `failed` while its latest
 * attempt failed, whatever an earlier one read (F113). A draft has none, and its list is not read.
 *
 * Whether the project has had one says whether its Conversations tab shows, the panel's and the
 * phone's: unknown until the list is read.
 *
 * The tab's one write (F44): the Stop of Pilot's answer in a conversation, by any person. Its
 * answer says at once that Pilot no longer answers there, into the list as read; then every screen
 * reads again. A refusal is the query client's toast, the API's words. Its form events are
 * `conversation.stop`'s.
 */

import { useQueryClient } from '@tanstack/react-query';
import { useGetProjectsConversationsByProjectId, usePostProjectsConversationsStopByProjectIdAndConversationId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { patchQueryData } from '@/lib/patch-query';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

type ConversationList = components['schemas']['ProjectConversationListSchema.de6f08c'];
export type Conversation = ConversationList['conversations'][number];

type ConversationsRead = ConversationList | 'pending' | 'failed';

const conversationsOf = (projectId: string) => ['getProjectsConversationsByProjectId', { path: { project_id: projectId } }];

/** The project's conversations as read. */
export function useProjectConversations(projectId: string): ConversationsRead {
  const query = useGetProjectsConversationsByProjectId({ path: { project_id: projectId } }, { refetchOnWindowFocus: 'always' });
  return query.error !== null ? 'failed' : (query.data ?? 'pending');
}

/**
 * Whether the project has had a conversation, a draft's if `draft`: undefined until its list is
 * read. A project's screen asks once, for its tabs; the read's `ui_state` events are
 * `panel.conversations`'s.
 */
export function useHadConversations(projectId: string, draft: boolean): boolean | undefined {
  const { data, isLoading, error } = useGetProjectsConversationsByProjectId(
    { path: { project_id: projectId } },
    { refetchOnWindowFocus: 'always', enabled: !draft },
  );
  useUiStateInstrumentation('panel.conversations', { isLoading, error });
  if (draft) return false;
  return data === undefined ? undefined : data.conversations.length > 0;
}

/** The signed-in person's Stop of Pilot's answer in a conversation of the project (F44). */
export function useStopConversation(projectId: string, conversationId: string) {
  const queryClient = useQueryClient();
  const mutation = usePostProjectsConversationsStopByProjectIdAndConversationId();
  const fields = { project: projectId, conversation: conversationId };
  const act = (): Promise<void> => {
    trackFormSubmit('conversation.stop', fields);
    return mutation.mutateAsync({ path: { project_id: projectId, conversation_id: conversationId } }).then(
      (stopped) => {
        trackFormSuccess('conversation.stop', fields);
        patchQueryData<ConversationList>(queryClient, conversationsOf(projectId), (list) =>
          list === undefined ? undefined : { conversations: list.conversations.map((each) => (each.id === stopped.id ? stopped : each)) },
        );
      },
      () => trackFormError('conversation.stop', fields),
    );
  };
  return { act, pending: mutation.isPending };
}

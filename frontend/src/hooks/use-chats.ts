/**
 * A project's chats as the Chat tab reads them (F40.3): the definition chat first where one exists,
 * then the project's chats in the order they opened, each open or closed, and whether Pilot is
 * answering in it; read again when the window regains the focus and on `project_changed`
 * (use-project-events.ts). `pending` while the read has nothing yet, `failed` while its latest
 * attempt failed, whatever an earlier one read (F113).
 */

import { useGetProjectsChatsByProjectId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

type ChatList = components['schemas']['ChatListSchema.f9d9b43'];
export type Chat = ChatList['chats'][number];

type ChatRead = ChatList | 'pending' | 'failed';

export function useProjectChats(projectId: string): ChatRead {
  const query = useGetProjectsChatsByProjectId({ path: { project_id: projectId } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('panel.chat', { isLoading: query.isLoading, error: query.error });
  if (query.error !== null) return 'failed';
  return query.data ?? 'pending';
}

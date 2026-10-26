/**
 * A work item's Stop and Resume (F67), the record's writes: Stop ends its session where it is, a
 * start held or under way included; Resume carries a stopped or failed one on through the gate.
 * The answer, the item's session as it stands, goes into its project's timeline as read; then
 * every screen reads again. A refusal is the query client's toast, the API's words. Their form
 * events are `timeline.stop`'s and `timeline.resume`'s, sent whether or not the item's actions
 * are still drawn when the answer comes. An act answers the item's session as it stands, or none
 * where it was refused.
 */

import { useParams } from '@tanstack/react-router';
import { useQueryClient } from '@tanstack/react-query';
import { moveWork } from '@/hooks/use-project-events';
import { usePostSessionsResumeBySessionId, usePostSessionsStopBySessionId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];
type State = Work['state'];

/** The states Stop is offered in, and Resume. */
export const STOPPABLE: readonly State[] = ['running', 'starting', 'held'];
export const RESUMABLE: readonly State[] = ['stopped', 'failed'];

type Mutation = ReturnType<typeof usePostSessionsStopBySessionId> | ReturnType<typeof usePostSessionsResumeBySessionId>;

function useAct(mutation: Mutation, form: string, itemId: string, from: readonly State[]) {
  const queryClient = useQueryClient();
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  const fields = { item: itemId };
  const act = (): Promise<Work | null> => {
    trackFormSubmit(form, fields);
    return mutation.mutateAsync({ path: { session_id: itemId } }).then(
      (work) => {
        trackFormSuccess(form, fields);
        moveWork(queryClient, projectId, itemId, work, from);
        return work;
      },
      () => {
        trackFormError(form, fields);
        return null;
      },
    );
  };
  return { act, pending: mutation.isPending };
}

export function useStop(itemId: string) {
  return useAct(usePostSessionsStopBySessionId(), 'timeline.stop', itemId, STOPPABLE);
}

export function useResume(itemId: string) {
  return useAct(usePostSessionsResumeBySessionId(), 'timeline.resume', itemId, RESUMABLE);
}

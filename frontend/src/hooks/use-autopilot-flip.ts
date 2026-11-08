/**
 * Auto pilot's switch: each flip a transition on the record by the person (F4.1). A refused flip
 * reads the project's head again, and where the project already stands as the flip asked, as after
 * a second tap's flip or one from a page left stale, the flip is answered as done and nothing is
 * toasted; any other refusal is the flip's error, which the query client's handler toasts.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { ProjectHead } from '@/hooks/use-projects';
import { toApiError } from '@/lib/api/api-error';
import { api } from '@/lib/api/client';
import { SENDER } from '@/lib/api/generated/hooks';

interface Flip {
  kind: 'autopilot_on' | 'autopilot_off';
  /** The switch's dialog's Yes (F4.2). */
  answer_confirmations?: boolean;
}

/** Auto pilot as the flip asked, and after the dialog's Yes no confirmation left that it would take. */
const standsAsAsked = (head: ProjectHead, { kind, answer_confirmations }: Flip) =>
  head.autopilot === (kind === 'autopilot_on') && !(answer_confirmations && head.autopilot_may_take > 0);

export function useAutopilotFlip(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (flip: Flip) => {
      const { error, response } = await api.POST('/api/projects/{project_id}/transitions', {
        params: { path: { project_id: projectId } },
        body: flip,
        headers: { 'X-Sender': SENDER },
      });
      if (!error) return;
      const head = ['getProjectsByProjectId', { path: { project_id: projectId } }];
      await queryClient.refetchQueries({ queryKey: head, exact: true });
      // The switch is drawn from the head as read.
      if (standsAsAsked(queryClient.getQueryData<ProjectHead>(head)!, flip)) return;
      throw toApiError(error, response.status);
    },
    // The flip stays pending until every query is read again, the head included: until then, a
    // second flip would ask for the same change.
    onSuccess: () => queryClient.invalidateQueries(),
  });
}

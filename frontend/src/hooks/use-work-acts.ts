/**
 * A work item's Stop and Resume (F67), the record's writes: Stop ends its session where it is, a
 * start held or under way included, and one idle with its nudge owed is owed it no more (W8);
 * Resume carries a stopped or failed one on through the gate. A job of Pilot's own takes neither;
 * Retry places a fresh job for a stopped or failed one's trigger, at the project's next place, and
 * marks the one retried. The answer, the item's session as it stands, goes into its project's
 * timeline as read; then every screen reads again. A refusal is the query client's toast, the
 * API's words, and the button pressed, disabled while its act was on its way, has the keyboard
 * focus back where it had it and nothing took it meanwhile (W7). Their form events are
 * `timeline.stop`'s, `timeline.resume`'s and `timeline.retry`'s, sent whether or not the item's
 * actions are still drawn when the answer comes. An act answers the item's session as it stands,
 * or none where it was refused.
 */

import { useLayoutEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useShownProject } from '@/hooks/use-project-address';
import { moveWork } from '@/hooks/use-project-events';
import {
  usePostSessionsResumeBySessionId,
  usePostSessionsRetryBySessionId,
  usePostSessionsStopBySessionId,
} from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';

type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];
type State = Work['state'];

/** The states a run is under way in, Stop offered; and Resume's, and a job's Retry until it is retried. */
export const STOPPABLE: readonly State[] = ['running', 'starting', 'held'];
export const RESUMABLE: readonly State[] = ['stopped', 'failed'];

/** Whether a worker's item offers Stop: while it runs, starts or is held, and idle with its nudge owed, its run halted or paused at its turn's end (W8). */
export const offersStop = (work: Work) => STOPPABLE.includes(work.state) || (work.state === 'idle' && work.nudge_owed);

/** The states a Stop's answer replaces the item's session in. */
const STOPPED_FROM: readonly State[] = [...STOPPABLE, 'idle'];

/**
 * Whether a job of Pilot's offers Retry: stopped or failed, not retried and owed no nudge — one
 * whose turn died at the quota wall is not at its end until its nudge's run ends (D078).
 */
export const offersRetry = (work: Work) => RESUMABLE.includes(work.state) && work.retried === null && !work.nudge_owed;

type Mutation =
  | ReturnType<typeof usePostSessionsStopBySessionId>
  | ReturnType<typeof usePostSessionsResumeBySessionId>
  | ReturnType<typeof usePostSessionsRetryBySessionId>;

/** The act of the button `pressed`, the item's session as it stands once it lands, or none where it was refused. */
type Act = (pressed: HTMLElement) => Promise<Work | null>;

function useAct(mutation: Mutation, form: string, itemId: string, from: readonly State[]): { act: Act; pending: boolean } {
  const queryClient = useQueryClient();
  const { id: projectId } = useShownProject();
  const pending = mutation.isPending;
  const focusBack = useFocusBack(pending);
  const fields = { item: itemId };
  const act: Act = (pressed) => {
    const focused = document.activeElement === pressed;
    trackFormSubmit(form, fields);
    return mutation.mutateAsync({ path: { session_id: itemId } }).then(
      (work) => {
        trackFormSuccess(form, fields);
        moveWork(queryClient, projectId, itemId, work, from);
        return work;
      },
      () => {
        trackFormError(form, fields);
        if (focused) focusBack(pressed);
        return null;
      },
    );
  };
  return { act, pending };
}

/**
 * The keyboard focus given back to a refused act's button once it is enabled again, where it is
 * still drawn and the focus is nowhere: disabled while its act was pending, it lost the focus to
 * the page.
 */
function useFocusBack(pending: boolean): (button: HTMLElement) => void {
  const button = useRef<HTMLElement | null>(null);
  const [refusals, setRefusals] = useState(0);
  useLayoutEffect(() => {
    const element = button.current;
    if (pending || element === null) return;
    button.current = null;
    const focused = document.activeElement;
    if (element.isConnected && (focused === null || focused === document.body || focused === element)) element.focus();
  }, [pending, refusals]);
  return (element) => {
    button.current = element;
    setRefusals((count) => count + 1);
  };
}

export function useStop(itemId: string) {
  return useAct(usePostSessionsStopBySessionId(), 'timeline.stop', itemId, STOPPED_FROM);
}

export function useResume(itemId: string) {
  return useAct(usePostSessionsResumeBySessionId(), 'timeline.resume', itemId, RESUMABLE);
}

export function useRetry(itemId: string) {
  return useAct(usePostSessionsRetryBySessionId(), 'timeline.retry', itemId, RESUMABLE);
}

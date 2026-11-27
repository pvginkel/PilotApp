/**
 * A task's answer as a read (F154.6): a route starts the task and answers its id at once, and the
 * server sends the task's events over the stream the page holds, to the person who started it
 * alone, its result in its `task_completed` event and its failure's words in `task_failed`. The
 * stream is heard from before the task is started, since its events may come before the start's
 * answer. A read cancelled stops listening; the task runs on.
 */

import type { SseContextValue } from '@/contexts/sse-context-base';

/** The stream's listener, `useSseContext().addEventListener`. */
export type Listen = SseContextValue['addEventListener'];

/** A task's event as the stream carries it (`backend/app/schemas/task_schema.py`, `TaskEvent`). */
interface TaskEvent {
  task_id: string;
  event_type: string;
  data: unknown;
}

/** The answer of the task `start` starts, which answers its id; `signal` cancels the wait. */
export async function taskAnswer<T>(listen: Listen, signal: AbortSignal, start: () => Promise<string>): Promise<T> {
  const heard: TaskEvent[] = [];
  let take: ((event: TaskEvent) => void) | null = null;
  const stop = listen('task_event', (data) => {
    const event = data as TaskEvent;
    if (take === null) heard.push(event);
    else take(event);
  });
  try {
    const id = await start();
    return await new Promise<T>((resolve, reject) => {
      const cancelled = () => reject(signal.reason);
      if (signal.aborted) {
        cancelled();
        return;
      }
      signal.addEventListener('abort', cancelled, { once: true });
      take = (event) => {
        if (event.task_id !== id) return;
        if (event.event_type === 'task_completed') resolve(event.data as T);
        else if (event.event_type === 'task_failed') reject(new Error((event.data as { error: string }).error));
      };
      heard.splice(0).forEach(take);
    });
  } finally {
    stop();
  }
}

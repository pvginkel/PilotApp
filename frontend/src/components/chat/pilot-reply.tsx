/**
 * Pilot's reply to one message (decision 14): bare in the column, without F38.2's border, a
 * little in from its left — the steps, the phantom while the turn runs, a failure in red — and
 * its working state, the cue. A finished turn stays as it streamed (decision 10, ruled
 * 2026-10-18).
 */

import { CircleAlert } from 'lucide-react';
import { activityOf } from '@/lib/chat/activity';
import { duration } from '@/lib/chat/format';
import type { Phantom } from '@/lib/chat/stream-state';
import type { TurnView } from '@/lib/chat/view';
import { useNow } from '@/hooks/use-now';
import { cn } from '@/lib/utils';
import { PhantomReply } from './phantom-reply';
import { ReplySteps } from './reply-steps';
import { StepLine } from './step-line';
import { WorkingCue } from './working-cue';

const fadeIn = 'animate-fade-in opacity-0';

export function ReplyBody({
  turn,
  phantom,
  liveFrom,
  streamed,
}: {
  turn: TurnView;
  phantom: Phantom | null;
  liveFrom: number | null;
  /** The text records this client saw stream in as the phantom. */
  streamed?: ReadonlySet<number>;
}) {
  const running = turn.state === 'running';
  const fresh = (seq: number) => liveFrom != null && seq >= liveFrom;

  return (
    <section className="mx-1.5 flex min-w-0 flex-col" data-turn={turn.turn} data-testid="chat.reply">
      <ReplySteps steps={turn.steps} liveFrom={liveFrom} streamed={streamed} />
      {running && phantom && <PhantomReply phantom={phantom} />}
      {turn.failure && (
        <div className={cn('mt-1', turn.endedAt && fresh(turn.lastSeq) && fadeIn)} data-testid="chat.failure">
          <StepLine icon={<CircleAlert className="size-3.5" aria-hidden />} tone="error" className="whitespace-normal [&>span]:whitespace-normal">
            {turn.failure}
          </StepLine>
        </div>
      )}
    </section>
  );
}

/** The cue of the turn in flight: what it is doing, a thinking block under way with its elapsed time. */
export function ReplyCue({ turn, phantom }: { turn: TurnView; phantom: Phantom | null }) {
  const now = useNow(!!phantom);
  const base = activityOf(turn, phantom);
  const activity =
    base.kind === 'thinking' && phantom ? { ...base, phase: `Thinking · ${duration(now - phantom.startedAt)}` } : base;
  return <WorkingCue activity={activity} />;
}

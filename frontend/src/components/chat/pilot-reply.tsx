/**
 * Pilot's reply to one message: bare in the column, without F38.2's border, 6px in from either
 * side (D002, over the chat mockup's decision 14) — the steps, the phantom while the turn runs, a
 * failure in red — and its working state, the cue. A finished turn stays as it streamed
 * (decision 10, ruled 2026-10-18). In the chat, an ended turn closes on Pilot's avatar and its
 * time, "· Stopped" by a stopped turn's and "· Failed" in red by a failed one's (F44).
 */

import { CircleAlert } from 'lucide-react';
import { sentFromHere } from '@/hooks/use-chats';
import { activityOf } from '@/lib/chat/activity';
import { duration } from '@/lib/chat/format';
import type { Phantom } from '@/lib/chat/stream-state';
import type { TurnView } from '@/lib/chat/view';
import { Avatar } from '@/components/shared/avatar';
import { Time } from '@/components/shared/time';
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

/**
 * The cue of the turn in flight: what it is doing, a thinking block under way with the time since
 * the turn's message was sent (C2): by this page's clock where this page sent it, else by the
 * message's record, else, where no person sent one, from the turn's first record.
 */
export function ReplyCue({ sessionId, turn, phantom }: { sessionId: string; turn: TurnView; phantom: Phantom | null }) {
  const now = useNow();
  const activity = activityOf(turn, phantom);
  if (activity.kind !== 'thinking') return <WorkingCue activity={activity} />;
  const since = sentFromHere(sessionId, turn.turn) ?? Date.parse(turn.person?.at ?? turn.startedAt);
  return <WorkingCue activity={{ ...activity, phase: `Thinking · ${duration(now - since)}` }} />;
}

/** Pilot's reply in the chat: its body, the cue while its turn runs, and its end once it has ended. */
export function PilotReply({
  sessionId,
  turn,
  phantom,
  liveFrom,
  streamed,
}: {
  /** The chat's session, whose turn it is. */
  sessionId: string;
  turn: TurnView;
  phantom: Phantom | null;
  liveFrom: number | null;
  streamed?: ReadonlySet<number>;
}) {
  return (
    <div className="flex min-w-0 flex-col" data-testid="chat.pilot">
      <ReplyBody turn={turn} phantom={phantom} liveFrom={liveFrom} streamed={streamed} />
      {turn.state === 'running' ? (
        <div className="mx-1.5">
          <ReplyCue sessionId={sessionId} turn={turn} phantom={phantom} />
        </div>
      ) : (
        turn.endedAt !== undefined && (
          <div className="mx-1.5 mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="chat.pilot.end">
            <Avatar who="pilot" size="xs" />
            <Time at={turn.endedAt} format="clock" />
            {turn.state === 'interrupted' && <span>· Stopped</span>}
            {turn.state === 'failed' && <span className="text-destructive-text">· Failed</span>}
          </div>
        )
      )}
    </div>
  );
}

/**
 * A work item's session log in the overlay (F69), at its own address over its project's timeline,
 * by the item's id, which is its session's (F97). Its head is "Session log" over the item's title,
 * its environment's link once its start has one, none for Pilot's own work (F26.3), and the
 * session's id, and Discuss, quoting the item (F69.1). Its body is the session's records rendered
 * as the chat renders a reply — the runs of calls, the sub-agents' cards, the phantom — streamed
 * from the first record while it is open (F40.3), one reply per turn, each ended one closing on
 * its time; it sticks to the end while it grows, and only the reader's own scrolling lets go
 * (F69.2). Its tail is the working cue while the session is held, starts or runs, else how it
 * ended: "Stopped by you · <time>", by whom else, by Pilot at the usage limit, the environment
 * stopped under it, "The turn ended · <time>", or "Failed" under the error (F69.2, F125, F135.6).
 * The tail follows the item's state as the timeline reads it, live, so that a Resume carries the
 * log on. An address that names no work item of the project reads "The session log did not load".
 */

import { useMemo, useRef, type RefObject } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { Check, CircleAlert, ScrollText, Square } from 'lucide-react';
import { DiscussButton } from '@/components/chat/discuss-button';
import { quoteOfItem } from '@/components/chat/discuss-quotes';
import { ReplyBody, ReplyCue } from '@/components/chat/pilot-reply';
import { StepLine } from '@/components/chat/step-line';
import { WorkingCue } from '@/components/chat/working-cue';
import { DidNotLoad, Overlay } from '@/components/overlay/overlay';
import { EnvironmentLink, LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { useSseContext } from '@/contexts/sse-context';
import { useChatStream } from '@/hooks/use-chat-stream';
import { usePerson } from '@/hooks/use-self';
import { useSessionTransport } from '@/hooks/use-session-transport';
import { useStickyBottom } from '@/hooks/use-sticky-bottom';
import { titleOf, type TimelineItem } from '@/hooks/use-timeline';
import { useGetProjectsTimelineByProjectId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import type { Activity } from '@/lib/chat/activity';
import type { ChatStreamState } from '@/lib/chat/stream-state';
import { buildChatView, type TurnView } from '@/lib/chat/view';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';
import { cn } from '@/lib/utils';
import { heldReasonLabel, sessionLogTail } from '@/lib/utils/status-labels';

type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];

interface SessionLogOverlayProps {
  projectId: string;
  sessionId: string;
}

export function SessionLogOverlay({ projectId, sessionId }: SessionLogOverlayProps) {
  const navigate = useNavigate();
  const close = () => void navigate({ to: '/projects/$projectId', params: { projectId } });
  const { data, error } = useGetProjectsTimelineByProjectId({ path: { project_id: projectId } });
  const item = data?.items.find((each) => each.id === sessionId);
  const work = item?.work ?? undefined;
  const failed = error !== null || (data !== undefined && work === undefined);
  const body = useRef<HTMLDivElement>(null);
  return (
    <Overlay
      showing={`session ${sessionId}`}
      titles={item && work && <Titles item={item} work={work} />}
      discuss={item && work && <DiscussButton quote={quoteOfItem(item)} title="Discuss: ask Pilot about this session" testId="overlay.discuss" />}
      foot={null}
      onClose={close}
      bodyRef={body}
    >
      {failed ? (
        <DidNotLoad what="The session log" />
      ) : (
        item && work && <SessionLog key={sessionId} item={item} work={work} body={body} />
      )}
    </Overlay>
  );
}

function Titles({ item, work }: { item: TimelineItem; work: Work }) {
  return (
    <>
      <h2 data-testid="overlay.title">
        <ScrollText className="icon" aria-hidden="true" /> Session log
      </h2>
      <div className="sub" data-testid="overlay.sub">
        <span data-testid="session-log.item">
          <LinkedText text={titleOf(item)} />
        </span>
        <span>·</span>
        {!work.pilots_own && work.environment !== null && (
          <>
            <EnvironmentLink environment={work.environment} testId="session-log.environment" />
            <span>·</span>
          </>
        )}
        <span className="mono" title="The session's id" data-testid="session-log.session">
          {item.id}
        </span>
      </div>
    </>
  );
}

/** Whether the session runs a turn, starts one, or is held at the gate. */
const isLive = (work: Work) => work.state === 'held' || work.state === 'starting' || work.state === 'running';

interface SessionLogProps {
  item: TimelineItem;
  work: Work;
  body: RefObject<HTMLDivElement | null>;
}

function SessionLog({ item, work, body }: SessionLogProps) {
  const { handle } = usePerson();
  const { isConnected } = useSseContext();
  const wrapper = useRef<HTMLDivElement>(null);
  useStickyBottom(body, wrapper, 'session-log');
  const stream = useChatStream(useSessionTransport(), item.id);
  useUiStateInstrumentation('session-log', {
    isLoading: stream.status === 'connecting' || stream.status === 'dropped',
    getReadyMetadata: () => ({ live: isConnected, lastSeq: stream.lastSeq }),
  });
  const live = isLive(work);
  const turns = useMemo(
    () => buildChatView(item.id, stream.records, { running: live }).flatMap((entry) => (entry.kind === 'turn' ? [entry] : [])),
    [item.id, stream.records, live],
  );
  const last = turns.at(-1)?.turn;
  const endedAt = (work.state === 'idle' ? item.done?.at : undefined) ?? last?.endedAt ?? null;
  const tail = sessionLogTail(work, handle, endedAt);

  return (
    <div ref={wrapper} className="session-log" data-testid="session-log">
      {turns.map(({ key, turn }) => (
        <div key={key} className="log-turn" data-testid="session-log.turn">
          <ReplyBody
            turn={turn}
            phantom={turn === last ? stream.phantom : null}
            liveFrom={stream.liveFrom}
            streamed={stream.streamed}
          />
          {turn !== last && <TurnEnd turn={turn} />}
        </div>
      ))}
      {tail === null ? (
        <div className="log-cue mx-1.5" data-testid="session-log.cue">
          <Cue work={work} last={last} stream={stream} />
        </div>
      ) : (
        <>
          {tail.mark === 'failed' && work.error !== null && last?.failure === undefined && (
            <StepLine icon={<CircleAlert className="size-3.5" aria-hidden />} tone="error" className="mx-1.5 whitespace-normal [&>span]:whitespace-normal">
              {work.error}
            </StepLine>
          )}
          <div className={cn('log-tail', tail.mark)} data-testid="session-log.tail" data-mark={tail.mark}>
            {tail.mark === 'stopped' ? (
              <Square className="icon" aria-hidden="true" />
            ) : tail.mark === 'failed' ? (
              <CircleAlert className="icon" aria-hidden="true" />
            ) : (
              <Check className="icon" aria-hidden="true" />
            )}
            <span>
              {tail.text}
              {tail.at !== null && (
                <>
                  {' · '}
                  <Time at={tail.at} format="clock" />
                </>
              )}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

/** An earlier turn's end: its time, and how it ended where it did not run out. */
function TurnEnd({ turn }: { turn: TurnView }) {
  if (turn.endedAt === undefined) return null;
  return (
    <div className="log-turn-end" data-testid="session-log.turn-end">
      <Time at={turn.endedAt} format="clock" />
      {turn.state === 'interrupted' && <span> · Stopped</span>}
      {turn.state === 'failed' && <span className="failed"> · Failed</span>}
    </div>
  );
}

/**
 * The working cue as the tail: why the gate holds the start; else what the turn in flight is
 * doing; else, before its first record, that it starts, or waits for Pilot.
 */
function Cue({ work, last, stream }: { work: Work; last: TurnView | undefined; stream: ChatStreamState }) {
  if (work.state === 'held' && work.held_reason !== null) {
    return <WorkingCue activity={{ kind: 'waiting', phase: heldReasonLabel(work.held_reason, work.held_running) }} />;
  }
  if (last?.state === 'running') return <ReplyCue turn={last} phantom={stream.phantom} />;
  const activity: Activity =
    work.state === 'running' ? { kind: 'waiting', phase: 'Waiting for Pilot' } : { kind: 'starting', phase: 'Starting' };
  return <WorkingCue activity={activity} />;
}

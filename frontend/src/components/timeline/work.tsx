/**
 * An open work item on the timeline (F26): a session Pilot started, updated in place as the
 * server's `work_moved` carries it (F80.2). Its head has the env chip, opening the environment in
 * KubeCoder, and "running N min" with a pulse while its turn runs (F26.1, F12). Under its title is
 * its one line (F26.2): the server's own words while its session comes up, or comes back while its
 * environment restarts; the working state and the latest step while it runs; why the gate holds
 * its start; "Stopped · <time>" with the cause of a stop made elsewhere; the error a failed start
 * or a turn ended in error left, shown as a stopped one is (F125). Its Session log opens the
 * session's records in the overlay (F26.3, F69).
 */

import { Link, useParams } from '@tanstack/react-router';
import { CircleAlert, ScrollText, Square } from 'lucide-react';
import { WorkingCue } from '@/components/chat/working-cue';
import { EnvironmentLink, LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { ItemHead } from '@/components/timeline/item-head';
import { useNow } from '@/hooks/use-now';
import { titleOf, type TimelineItem } from '@/hooks/use-timeline';
import type { components } from '@/lib/api/generated/types';
import { workLine } from '@/lib/utils/status-labels';

type Work = components['schemas']['TimelineSchema.1fdd8ae.WorkSchema'];

/** How often "running N min" is counted again, in milliseconds. */
const TICK = 15_000;

export function WorkItem({ item }: { item: TimelineItem }) {
  // The API gives every work item its session.
  const work = item.work!;
  return (
    <div className="item-body">
      <ItemHead item={item}>
        <span className="chip mono env">
          <EnvironmentLink environment={work.environment} testId="timeline.work.environment" />
        </span>
        {work.state === 'running' && work.started_at !== null && <Running since={work.started_at} />}
      </ItemHead>
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      <Line work={work} />
      <div className="item-actions">
        <SessionLog item={item} />
      </div>
    </div>
  );
}

/** "running N min" from when its run began, with a pulse. */
function Running({ since }: { since: string }) {
  // performance.timeOrigin + performance.now() is the wall clock's time, in milliseconds.
  const now = performance.timeOrigin + useNow(true, TICK);
  return (
    <span className="work-live" data-testid="timeline.work.running">
      <span className="pulse" aria-hidden="true" />
      running {span(now - new Date(since).getTime())}
    </span>
  );
}

/** A run's length as the head counts it: "under a minute", "12 min", "1 h 5 min", "3 h", "2 days". */
function span(ms: number): string {
  const minutes = Math.round(Math.max(ms, 0) / 60_000);
  if (minutes < 1) return 'under a minute';
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return minutes % 60 && hours < 6 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
  return `${Math.round(hours / 24)} days`;
}

function Line({ work }: { work: Work }) {
  const line = workLine(work);
  if (line === null) return null;
  const shared = { 'data-testid': 'timeline.work.line', 'data-state': work.state };
  switch (line.kind) {
    case 'cue':
      return (
        <div className="work-line" {...shared}>
          <WorkingCue activity={line.activity} />
          {line.step !== null && (
            <span className="step" title={line.step} data-testid="timeline.work.step">
              {line.step}
            </span>
          )}
        </div>
      );
    case 'stopped':
      return (
        <div className="work-line ended" {...shared}>
          <Square className="icon" aria-hidden="true" />
          <span>
            Stopped
            {line.at !== null && (
              <>
                {' · '}
                <Time at={line.at} format="clock" />
              </>
            )}
            {line.cause !== null && ` · ${line.cause}`}
          </span>
        </div>
      );
    case 'failed':
      return (
        <div className="work-line ended" {...shared}>
          <CircleAlert className="icon" aria-hidden="true" />
          <span>
            Failed
            {line.error !== null && ` · ${line.error}`}
          </span>
        </div>
      );
    default: {
      const unknown: never = line;
      return unknown;
    }
  }
}

/** The session log in the overlay, at its address under the project's, by the item's id, its session's. */
function SessionLog({ item }: { item: TimelineItem }) {
  const { projectId } = useParams({ from: '/_shell/projects/$projectId' });
  return (
    <Link
      to="/projects/$projectId/sessions/$sessionId"
      params={{ projectId, sessionId: item.id }}
      className="btn btn-sm"
      data-testid="timeline.work.session-log"
    >
      <ScrollText className="icon" aria-hidden="true" />
      Session log
    </Link>
  );
}

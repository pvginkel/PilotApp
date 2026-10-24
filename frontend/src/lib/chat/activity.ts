/**
 * What the turn in flight is doing, in a few words, for the working cue (decision 6): the
 * phantom's block, else the server's latest line while the session comes up, or comes up again
 * under the turn, in its own words — those lines show nowhere else, and are gone once Pilot's next
 * step lands — else the call still running, else the sub-agent's progress.
 */

import type { Phantom } from './stream-state';
import type { Step, TurnView } from './view';

export type ActivityKind = 'waiting' | 'starting' | 'thinking' | 'writing' | 'tool' | 'agent' | 'working';

export interface Activity {
  kind: ActivityKind;
  /** The phase alone, for a cue under steps that already show the specifics: "Working". */
  phase: string;
}

/** A line's words without their closing ellipsis: "Starting Example-1". */
export const phaseOf = (text: string) => text.replace(/\s*(…|\.\.\.)$/, '');

function runningIn(steps: Step[]): Activity | null {
  for (let i = steps.length - 1; i >= 0; i--) {
    const s = steps[i]!;
    if (s.kind !== 'tool') continue;
    const { call } = s;
    if (call.agent?.status === 'running') {
      return { kind: 'agent', phase: `Waiting for the ${call.agent.type} agent` };
    }
    if (!call.result && !call.stopped) return { kind: 'tool', phase: 'Working' };
  }
  return null;
}

export function activityOf(turn: TurnView, phantom: Phantom | null): Activity {
  if (phantom) {
    if (phantom.block === 'thinking') return { kind: 'thinking', phase: 'Thinking' };
    if (phantom.block === 'text') return { kind: 'writing', phase: 'Writing' };
    if (phantom.block === 'tool_use') return { kind: 'tool', phase: 'Working' };
  }
  const line = turn.comingUp?.payload;
  if (line?.type === 'starting' || line?.type === 'restarting') return { kind: 'starting', phase: phaseOf(line.text) };
  const running = runningIn(turn.steps);
  if (running) return running;
  if (!turn.steps.length) return { kind: 'waiting', phase: 'Waiting for Pilot' };
  return { kind: 'working', phase: 'Working' };
}

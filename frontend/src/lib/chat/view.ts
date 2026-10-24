/**
 * The records as the view shows them (ruling 11: the formatting is the client's): a person's
 * message, then Pilot's reply to it as steps — text, thinking, tool calls with their results, a
 * sub-agent's own steps folded under its call — and the separator where a chat closed.
 *
 * What shows is an allowlist (DesignAssistant's chat-panel rule, decision 9): hooks, `init`,
 * `status`, rate limits, `claude`'s own `result` lines, the background-task list and anything
 * unknown are left out, and so is a block whose text is empty.
 *
 * A record outside any Turn — the server's lines while the session comes up, a failed start —
 * falls in the Turn in flight, else in the next: the one numbered after the last. A Turn ends at
 * its `result`, at a failed send or start, at the environment stopped under it, or, ended with no
 * record of it, where a later Turn's records begin; a call or a sub-agent still running then was
 * stopped with it.
 */

import type { ChatRecord, Effect, SendRecord, ServerRecord } from './records';
import { isAssistant, isMainThread, isSystem, isUser, resultText, type AssistantLine, type SystemLine } from './claude-lines';

interface ToolResultView {
  text: string;
  isError: boolean;
  seq: number;
}

export interface AgentView {
  type: string;
  description: string;
  status: 'running' | 'completed' | 'failed' | 'stopped';
  /** The latest `task_progress` line: "Running List headless dir…". */
  progress?: string;
  /** What it reported (`task_notification`'s summary). */
  summary?: string;
  steps: Step[];
}

export interface ToolCallView {
  id: string;
  name: string;
  input: Record<string, unknown>;
  result?: ToolResultView;
  /** Its turn ended with no result for it. */
  stopped?: boolean;
  /** Set on an Agent call: its sub-agent. */
  agent?: AgentView;
  /** What a `pilot-store` call changed (the server's effect records). */
  effects: Effect[];
}

export type Step =
  | { kind: 'text'; seq: number; text: string }
  | { kind: 'thinking'; seq: number; text: string; durationMs?: number }
  | { kind: 'tool'; seq: number; call: ToolCallView }
  | { kind: 'error'; seq: number; text: string };

type TurnState = 'running' | 'done' | 'interrupted' | 'failed';

export interface TurnView {
  turn: number;
  person?: SendRecord;
  /** Pilot's reply, in order. */
  steps: Step[];
  /** The server's latest line while the session comes up, or comes up again, until Pilot's next
   *  step (F81, F71): the cue shows it. */
  comingUp: ServerRecord | null;
  state: TurnState;
  /** Why it failed, when it did: a failed send or start (F125), an API error, the turn's error. */
  failure?: string;
  firstSeq: number;
  lastSeq: number;
  startedAt: string;
  /** When its last record was written. */
  lastAt: string;
  endedAt?: string;
}

type ChatItem = { kind: 'turn'; key: string; turn: TurnView } | { kind: 'closed'; key: string; at: string; seq: number };

const textOf = (line: AssistantLine) =>
  line.message.content
    .filter((b) => b.type === 'text')
    .map((b) => (b.type === 'text' ? b.text : ''))
    .join('');

/**
 * `running`: whether the Session has a Turn in flight. When it has none, a Turn its records
 * leave open ended unrecorded, at its last record.
 */
export function buildChatView(chatId: string, records: readonly ChatRecord[], { running = true } = {}): ChatItem[] {
  const items: ChatItem[] = [];
  const calls = new Map<string, ToolCallView>();
  const turnCalls = new Map<number, ToolCallView[]>();
  const turns = new Map<number, TurnView>();
  let turn: TurnView | null = null;

  const end = (t: TurnView, state: TurnState, at: string) => {
    t.state = state;
    t.endedAt = at;
    for (const call of turnCalls.get(t.turn) ?? []) {
      if (!call.result) call.stopped = true;
      if (call.agent?.status === 'running') call.agent.status = 'stopped';
    }
  };

  const open = (r: ChatRecord): TurnView => {
    const number = r.turn ?? (turn === null ? 1 : turn.state === 'running' ? turn.turn : turn.turn + 1);
    const seen = turns.get(number);
    if (seen) return seen;
    if (turn?.state === 'running') end(turn, 'done', turn.lastAt);
    turn = {
      turn: number,
      steps: [],
      comingUp: null,
      state: 'running',
      firstSeq: r.seq,
      lastSeq: r.seq,
      startedAt: r.at,
      lastAt: r.at,
    };
    turns.set(number, turn);
    items.push({ kind: 'turn', key: `${chatId}:${number}`, turn });
    return turn;
  };

  /** Where a line's steps go: the main thread's reply, or its sub-agent's steps. */
  const stepsFor = (t: TurnView, parent: string | null | undefined): Step[] => {
    if (!parent) return t.steps;
    const call = calls.get(parent);
    if (!call) return t.steps;
    call.agent ??= { type: 'Sub', description: '', status: 'running', steps: [] };
    return call.agent.steps;
  };

  const onSystem = (line: SystemLine) => {
    const call = line.tool_use_id ? calls.get(line.tool_use_id) : undefined;
    switch (line.subtype) {
      case 'task_started':
        if (call?.agent) call.agent.status = 'running';
        return;
      case 'task_progress':
        if (call?.agent && line.description) call.agent.progress = line.description;
        return;
      case 'task_notification':
        if (call?.agent) {
          call.agent.status = line.status === 'completed' ? 'completed' : line.status === 'failed' ? 'failed' : 'stopped';
          call.agent.summary = typeof line.summary === 'string' ? line.summary : undefined;
          call.agent.progress = undefined;
        }
        return;
    }
  };

  for (const r of records) {
    if (r.kind === 'send') {
      const t = open(r);
      t.person = r;
      continue;
    }
    if (r.kind === 'server' && r.payload.type === 'closed') {
      items.push({ kind: 'closed', key: `${chatId}:closed`, at: r.at, seq: r.seq });
      turn = null;
      continue;
    }
    const t = open(r);
    t.lastSeq = r.seq;
    t.lastAt = r.at;

    if (r.kind === 'result') {
      const { isError, interrupted, result } = r.payload;
      if (isError && !t.failure) t.failure = result || 'The turn failed.';
      end(t, interrupted ? 'interrupted' : isError ? 'failed' : 'done', r.at);
      continue;
    }

    if (r.kind === 'server') {
      const ev = r.payload;
      switch (ev.type) {
        case 'starting':
        case 'restarting':
          t.comingUp = r;
          break;
        case 'start-failed':
        case 'send-failed':
          t.failure = ev.reason;
          end(t, 'failed', r.at);
          break;
        case 'environment-stopped':
          end(t, 'interrupted', r.at);
          break;
        case 'effect':
          calls.get(ev.toolUseId)?.effects.push(ev.effect);
          break;
        case 'session-gone':
          break;
      }
      continue;
    }

    const line = r.payload;
    if (typeof line === 'string') continue;
    if (isAssistant(line)) {
      t.comingUp = null;
      const steps = stepsFor(t, line.parent_tool_use_id);
      if (line.is_api_error_message || line.error) {
        // The main thread's error is the turn's failure, shown once; a sub-agent's is its step.
        const text = textOf(line);
        if (isMainThread(line)) t.failure = text;
        else steps.push({ kind: 'error', seq: r.seq, text });
        continue;
      }
      for (const block of line.message.content) {
        if (block.type === 'text') {
          if (block.text.trim()) steps.push({ kind: 'text', seq: r.seq, text: block.text });
        } else if (block.type === 'thinking') {
          steps.push({ kind: 'thinking', seq: r.seq, text: block.thinking, durationMs: line.thinking_duration_ms });
        } else if (block.type === 'tool_use') {
          const call: ToolCallView = { id: block.id, name: block.name, input: block.input, effects: [] };
          if (block.name === 'Agent' || block.name === 'Task') {
            call.agent = {
              type: typeof block.input.subagent_type === 'string' ? block.input.subagent_type : 'Sub',
              description: typeof block.input.description === 'string' ? block.input.description : '',
              status: 'running',
              steps: [],
            };
          }
          calls.set(block.id, call);
          turnCalls.set(t.turn, [...(turnCalls.get(t.turn) ?? []), call]);
          steps.push({ kind: 'tool', seq: r.seq, call });
        }
      }
    } else if (isUser(line) && Array.isArray(line.message.content)) {
      t.comingUp = null;
      for (const block of line.message.content) {
        if (block.type !== 'tool_result') continue;
        const call = calls.get(block.tool_use_id);
        if (call) call.result = { text: resultText(block), isError: !!block.is_error, seq: r.seq };
      }
    } else if (isSystem(line)) {
      onSystem(line);
    }
  }

  const latest = items.at(-1);
  if (!running && latest?.kind === 'turn' && latest.turn.state === 'running') end(latest.turn, 'done', latest.turn.lastAt);
  return items;
}

/** The steps a reply shows: all but its thinking, which the cue shows while it runs (ruling 2). */
export const shownSteps = (steps: Step[]): Step[] => steps.filter((s) => s.kind !== 'thinking');

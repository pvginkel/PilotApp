/**
 * One Session's stream on the client: the records applied in order, and the phantom reply (§4).
 *
 * Records are applied by number: one at or below the last applied is a repeat and dropped
 * (DesignAssistant's use-timeline-sse rule), so a reconnect after the last record held cannot
 * double one. The phantom is built from a main-thread block's marker (`content_block_start`)
 * and the text deltas after it, and never stored:
 *
 * - a delta whose block's marker this client has not seen is dropped (ruling 15): a viewer who
 *   opened, or reconnected, mid-block sees that block when its record lands;
 * - it goes when the main thread's next `assistant` record arrives, whatever it holds (ruling
 *   14), at the turn's end, and when the stream drops (ruling 16); other records leave it.
 *
 * Each delta keeps where it starts and when it came, for the new text's fade (decision 1).
 */

import type { ChatFrame, ChatRecord } from './records';
import { isAssistant, isMainThread } from './claude-lines';

export interface Delta {
  /** Where it starts in the phantom's text. */
  at: number;
  /** The client's clock when it came. */
  t: number;
}

export interface Phantom {
  /** The content block's index in its API message. */
  index: number;
  block: 'text' | 'thinking' | 'tool_use' | string;
  /** A tool call's name, from its marker. */
  name?: string;
  /** The text deltas so far: a text block's only. */
  text: string;
  deltas: Delta[];
  /** The client's clock when the marker came: how long the block has been under way. */
  startedAt: number;
}

export interface ChatStreamState {
  records: ChatRecord[];
  lastSeq: number;
  /** Records numbered from here on came live, after the stream caught up: they fade in. */
  liveFrom: number | null;
  phantom: Phantom | null;
  /** The text records whose block this client saw stream in: they replace the phantom, so they
   *  do not fade in again. */
  streamed: ReadonlySet<number>;
  status: 'connecting' | 'open' | 'dropped' | 'ended';
}

export const initialStreamState: ChatStreamState = {
  records: [],
  lastSeq: 0,
  liveFrom: null,
  phantom: null,
  streamed: new Set(),
  status: 'connecting',
};

type StreamAction = { type: 'connecting' } | { type: 'frame'; frame: ChatFrame; now: number } | { type: 'dropped' };

const endsPhantom = (record: ChatRecord) =>
  record.kind === 'result' ||
  (record.kind === 'claude' && typeof record.payload !== 'string' && isAssistant(record.payload) && isMainThread(record.payload)) ||
  (record.kind === 'server' && (record.payload.type === 'send-failed' || record.payload.type === 'environment-stopped'));

function applyRecord(state: ChatStreamState, record: ChatRecord): ChatStreamState {
  if (record.seq <= state.lastSeq) return state;
  const ends = endsPhantom(record);
  const replaces = ends && record.kind === 'claude' && state.phantom?.block === 'text' && state.phantom.text !== '';
  return {
    ...state,
    records: [...state.records, record],
    lastSeq: record.seq,
    phantom: ends ? null : state.phantom,
    streamed: replaces ? new Set(state.streamed).add(record.seq) : state.streamed,
  };
}

export function streamReducer(state: ChatStreamState, action: StreamAction): ChatStreamState {
  switch (action.type) {
    case 'connecting':
      return { ...state, status: 'connecting', phantom: null };
    case 'dropped':
      return { ...state, status: 'dropped', phantom: null };
    case 'frame': {
      const { frame } = action;
      switch (frame.type) {
        case 'record':
          return applyRecord(state, frame.record);
        case 'caught-up':
          return { ...state, status: 'open', liveFrom: state.liveFrom ?? state.lastSeq + 1 };
        case 'end':
          return { ...state, status: 'ended', phantom: null, liveFrom: state.liveFrom ?? state.lastSeq + 1 };
        case 'partial': {
          const ev = frame.line.event;
          if (ev.type === 'content_block_start') {
            return {
              ...state,
              phantom: {
                index: ev.index,
                block: ev.content_block.type,
                name: ev.content_block.name,
                text: '',
                deltas: [],
                startedAt: action.now,
              },
            };
          }
          if (ev.type === 'content_block_delta' && ev.delta.type === 'text_delta') {
            const p = state.phantom;
            if (!p || p.index !== ev.index || p.block !== 'text') return state;
            const delta = { at: p.text.length, t: action.now };
            return { ...state, phantom: { ...p, text: p.text + ev.delta.text, deltas: [...p.deltas, delta] } };
          }
          return state;
        }
      }
    }
  }
  return state;
}

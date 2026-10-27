/**
 * A Session's records as the server writes and streams them (features.md F40; database.md
 * decision 49; docs/sessions.md, "The stream").
 *
 * A Session is a flat list of records in the order they came in, numbered gaplessly from 1: a
 * person's message (`send`, its words the Turn's), every line of the session's raw stream but the
 * partial `stream_event` lines (`claude`, verbatim, with its raw-file offset), the worker's frame
 * that ends a Turn (`result`), and the server's own (`server`). The client formats; the server
 * keeps the lines as they came. The shapes are the API's; a payload is typed as the server
 * writes it.
 */

import type { components } from '@/lib/api/generated/types';
import type { ClaudeLine, StreamEventLine } from './claude-lines';

type Schemas = components['schemas'];
type ClaudeRecordSchema = Schemas['SessionRecordPageSchema.01118bb.ClaudeRecordSchema'];
type ResultRecordSchema = Schemas['SessionRecordPageSchema.01118bb.ResultRecordSchema'];
type ServerRecordSchema = Schemas['SessionRecordPageSchema.01118bb.ServerRecordSchema'];
type StopCause = Schemas['TimelineSchema.1fdd8ae.StopCause'];
export type CloseCause = Schemas['ChatListSchema.f9d9b43.CloseCause'];

/** A person's message, written at the send: `claude` does not replay it. */
export type SendRecord = Schemas['SessionRecordPageSchema.01118bb.SendRecordSchema'];

/** One line of the session's raw stream, as `claude` printed it: its JSON, or its text. */
type ClaudeRecord = Omit<ClaudeRecordSchema, 'payload'> & { payload: ClaudeLine | string };

/** The worker's terminal `result` frame: the turn's end and its outcome. */
interface ResultFrame {
  turn: number;
  /** The turn's answer; its error when `isError`. */
  result: string | null;
  isError: boolean;
  interrupted: boolean;
}

type ResultRecord = Omit<ResultRecordSchema, 'payload'> & { payload: ResultFrame };

/** The server's own: what no stream line says. */
export type ServerRecord = Omit<ServerRecordSchema, 'payload'> & { payload: ServerEvent };

type ServerEvent =
  /** While the session comes up (F26.2, F81): "Starting <environment>…", "Creating the session…". */
  | { type: 'starting'; text: string }
  /** The environment restarting under the Turn in flight (F71): "<environment> is restarting…". */
  | { type: 'restarting'; text: string }
  /** The start failed (F125). */
  | { type: 'start-failed'; reason: string }
  /** The send failed before a turn ran (F125). */
  | { type: 'send-failed'; reason: string }
  /** The controller session is gone, and a new one carries the conversation on. */
  | { type: 'session-gone'; reason: string }
  /** The environment stopped under the Turn, a stop made elsewhere (F71, F69.2): the Turn's last record. */
  | { type: 'environment-stopped'; cause: StopCause; reason: string }
  /** A document the session registered, its file not read at its run's end (ruling D1): it keeps no text. */
  | { type: 'read-failed'; item: string; path: string; reason: string }
  /** A document the session registered, closed, its file not written back (F65.1). */
  | { type: 'write-back-refused'; item: string; path: string; reason: string }
  /**
   * A call changed the record (F41) — a `pilot-store` call, or a worker's `register_document` or
   * `attach_file` — so the client links without reading its result. `toolUseId` is the call's,
   * null where its client sent none.
   */
  | { type: 'effect'; toolUseId: string | null; effect: Effect }
  /** The chat closed (F130.1): after its timeout, at Create project, Finish, Reopen or Archive. */
  | { type: 'closed'; cause: CloseCause };

export interface Effect {
  /** F41's verbs: "Answered", "Added", "Marked read", "Stopped", "Finished", "Registered", "Attached". */
  verb: string;
  /** What it changed: "D1 · Which search API", "Action · Store the key", "inbox/3". */
  label: string;
  /** The item the effect goes to. */
  itemId?: string;
  /** The block in it, by its id `<item id>/<local id>`. */
  blockId?: string;
}

export type ChatRecord = SendRecord | ClaudeRecord | ResultRecord | ServerRecord;

/**
 * What a Session's stream gives the client: its records from an offset on, then each new one as
 * it is written; between them, live, the partial lines the server forwards and never stores: a
 * main-thread block's `content_block_start` and the `text_delta`s after it, verbatim.
 */
export type ChatFrame =
  | { type: 'record'; record: ChatRecord }
  | { type: 'partial'; line: StreamEventLine }
  /** Every record written before the stream opened has been given: what follows is live (fades in). */
  | { type: 'caught-up' }
  /** The Session's stream has ended, after its last record: it is `ended` or `failed`. */
  | { type: 'end' };

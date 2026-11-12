/**
 * A person's message from its Send until the chat shows its record (R21): a stand-in, which stands
 * at the chat's end at once as the message will. Its record takes its place where the stream of
 * the project's latest chat brings it: the earliest message of this person's with its words that
 * the stream did not hold at the Send, whether it comes before the server's answer to the send or
 * after. A send the server refuses takes its stand-in away. A new project's first message stands
 * the same way, with the new project until its draft is made and with the draft from then on, so
 * that it shows through the switch to the draft's screen (R42). Kept in the page, by the project.
 */

import { useSyncExternalStore } from 'react';
import { wallClock } from '@/hooks/use-now';
import type { QuoteRef } from '@/lib/chat/quotes';
import type { ChatRecord } from '@/lib/chat/records';

/** Where a new project's first message stands until its draft is made. */
export const NEW_PROJECT = 'new';

export interface StandIn {
  id: number;
  /** The project it was sent to. */
  project: string;
  /** The message as sent, a quote's tag before the words. */
  message: string;
  /** What it quotes. */
  quote: QuoteRef | null;
  /** When Send was pressed, by this page's clock. */
  at: string;
  /** The server has not answered its send yet. */
  onWay: boolean;
  /** Its record shows in its place, ahead of the server's answer to its send. */
  landed: boolean;
  /** The number of the last record each chat's stream held at the Send, by the chat. */
  held: ReadonlyMap<string, number>;
}

const NONE: readonly StandIn[] = [];
const NOTHING: ReadonlyMap<number, StandIn> = new Map();

/** Every stand-in that stands or is on its way, in the order they were sent. */
let all: readonly StandIn[] = [];
/** Those that stand, by the project. */
let standing: ReadonlyMap<string, readonly StandIn[]> = new Map();
let lastId = 0;
const listeners = new Set<() => void>();
/** The number of the last record each chat's stream holds, by the chat. */
const held = new Map<string, number>();
/** The records that took a stand-in's place, each `<chat>:<seq>`. */
const landed = new Set<string>();

function update(change: (standIns: readonly StandIn[]) => readonly StandIn[]): void {
  all = change(all);
  const next = new Map<string, StandIn[]>();
  for (const standIn of all) if (!standIn.landed) next.set(standIn.project, [...(next.get(standIn.project) ?? []), standIn]);
  standing = next;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Send was pressed on `message` for the project: its stand-in, by its id. */
export function standInFor(project: string, message: string, quote: QuoteRef | null): number {
  const id = ++lastId;
  const at = new Date(wallClock()).toISOString();
  update((standIns) => [...standIns, { id, project, message, quote, at, onWay: true, landed: false, held: new Map(held) }]);
  return id;
}

/** The server took the stand-in's message; a new project's, for the draft `project` it made. */
export function standInTaken(id: number, project?: string): void {
  update((standIns) =>
    standIns.flatMap((each) => (each.id !== id ? [each] : each.landed ? [] : [{ ...each, onWay: false, project: project ?? each.project }])),
  );
}

/** The server refused the stand-in's message. */
export function standInRefused(id: number): void {
  update((standIns) => standIns.filter((each) => each.id !== id));
}

/** The chat's stream holds its records up to `seq`. */
export function streamHolds(chatId: string, seq: number): void {
  held.set(chatId, seq);
}

/**
 * The stand-ins the chat's records take the place of, by the record's number: each message of
 * `me` the stream did not hold at a stand-in's Send, for the earliest stand-in of its words.
 */
export function landings(standIns: readonly StandIn[], chatId: string, records: readonly ChatRecord[], me: string): ReadonlyMap<number, StandIn> {
  if (standIns.length === 0) return NOTHING;
  const waiting = [...standIns];
  const found = new Map<number, StandIn>();
  for (const record of records) {
    if (record.kind !== 'send' || record.author !== me) continue;
    const index = waiting.findIndex((each) => each.message === record.message && record.seq > (each.held.get(chatId) ?? 0));
    if (index >= 0) found.set(record.seq, waiting.splice(index, 1)[0]!);
  }
  return found.size === 0 ? NOTHING : found;
}

/** The chat's record `seq` shows in the stand-in's place. */
export function standInLanded(id: number, chatId: string, seq: number): void {
  landed.add(`${chatId}:${seq}`);
  update((standIns) => standIns.flatMap((each) => (each.id !== id ? [each] : each.onWay ? [{ ...each, landed: true }] : [])));
}

/** Whether the chat's record took a stand-in's place on this page. */
export const tookStandInsPlace = (chatId: string, seq: number): boolean => landed.has(`${chatId}:${seq}`);

/** The project's stand-ins that stand, in the order they were sent. */
export function useStandIns(project: string): readonly StandIn[] {
  return useSyncExternalStore(subscribe, () => standing.get(project) ?? NONE);
}

/** The project's message on its way to the server: its stand-in, whether it stands or its record does. */
export function useSendOnWay(project: string): StandIn | undefined {
  return useSyncExternalStore(subscribe, () => all.find((each) => each.project === project && each.onWay));
}

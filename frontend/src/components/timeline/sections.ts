/**
 * A settled section (F31.5): a block's own section (F30.9) whose answer is Pilot's, settled or
 * deferred, stands collapsed to its line until it is opened, by a click on the line, a segment of
 * its document's bar (F33) or the block's address (F97), and from then on stands open on that
 * page. A person's answer is not Pilot's, so it opens the section for good, and Undo, which never
 * gives an answer back to Pilot, leaves it open.
 */

import { createContext, useState } from 'react';
import { isAnswered, type Block, type BodyPart } from '@/hooks/use-timeline';

interface Sections {
  /** The blocks, by `<item>/<block>`, whose sections stand open. */
  opened: ReadonlySet<string>;
  open: (key: string) => void;
}

export const SectionsContext = createContext<Sections>({ opened: new Set(), open: () => undefined });

/** The sections opened on a page of its own; `at`, the block the page is at by `<item>/<block>`, among them. */
export function useSections(at: string | null): Sections {
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  // In the render that brings it, so the block is drawn by the time the page goes to it.
  if (at !== null && !opened.has(at)) setOpened(new Set([...opened, at]));
  const open = (key: string) => setOpened((current) => (current.has(key) ? current : new Set([...current, key])));
  return { opened, open };
}

/** Whether the block's section collapses while it is not opened: its own section, answered, its answer Pilot's. */
export const isSettled = (block: Block) => block.section !== null && block.by?.kind === 'agent' && isAnswered(block);

/** What a document's body draws: a part as it is, or the blocks of consecutive collapsed sections, each its line. */
type Piece = { type: 'part'; part: BodyPart; index: number } | { type: 'settled'; blocks: Block[] };

/** The body's pieces, every part of a collapsed section standing in its block's line. */
export function piecesOf(body: BodyPart[], collapsed: (block: Block) => boolean): Piece[] {
  const settled = new Map(
    body.flatMap((part): [string, Block][] => (part.type === 'block' && collapsed(part.block) ? [[part.block.id, part.block]] : [])),
  );
  const pieces: Piece[] = [];
  body.forEach((part, index) => {
    const owner = part.type === 'prose' ? part.section : part.block.section === null ? null : part.block.id;
    const block = owner === null ? undefined : settled.get(owner);
    if (block === undefined) {
      pieces.push({ type: 'part', part, index });
      return;
    }
    // A section's parts and its block stand together: its line goes once, in its block's place.
    if (part.type === 'prose') return;
    const last = pieces.at(-1);
    if (last?.type === 'settled') last.blocks.push(block);
    else pieces.push({ type: 'settled', blocks: [block] });
  });
  return pieces;
}

/**
 * A settled section (F31.5): a block's own section (F30.9) whose answer is Pilot's, settled or
 * deferred, stands collapsed to its line until it is opened, by a click on the line, a segment of
 * its document's bar (F33) or the block's address (F97), and from then on stands open on that
 * page. A person's answer is not Pilot's, so it opens the section for good, and Undo, which never
 * gives an answer back to Pilot, leaves it open. A held block's section (F31.7) is its block's line
 * whether opened or not, the line over the section once opened (block.tsx).
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

/**
 * What a document's body draws: a part as it is, the blocks of consecutive collapsed sections, each
 * its line, or a held block with the parts of its own section, in their order, the block among them.
 */
type Piece =
  | { type: 'part'; part: BodyPart; index: number }
  | { type: 'settled'; blocks: Block[] }
  | { type: 'held'; block: Block; section: BodyPart[] };

/**
 * The body's pieces, every part of a collapsed section standing in its block's line, and every part
 * of a held block's section in its block's piece.
 */
export function piecesOf(body: BodyPart[], collapsed: (block: Block) => boolean, held: (block: Block) => boolean): Piece[] {
  const blocks = body.flatMap((part) => (part.type === 'block' ? [part.block] : []));
  const settled = new Map(blocks.filter((block) => !held(block) && collapsed(block)).map((block) => [block.id, block]));
  const sections = new Map(blocks.filter(held).map((block): [string, BodyPart[]] => [block.id, []]));
  const pieces: Piece[] = [];
  body.forEach((part, index) => {
    const owner = part.type === 'prose' ? part.section : part.block.section === null ? null : part.block.id;
    const section = owner === null ? undefined : sections.get(owner);
    if (section !== undefined) {
      // A section's parts and its block stand together: the block's piece takes them all.
      section.push(part);
      if (part.type === 'block') pieces.push({ type: 'held', block: part.block, section });
      return;
    }
    if (part.type === 'block' && held(part.block)) {
      pieces.push({ type: 'held', block: part.block, section: [part] });
      return;
    }
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

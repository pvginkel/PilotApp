/**
 * A settled section (F31.5): a block's own section (F30.9) whose answer is Pilot's, settled or
 * deferred, stands collapsed to its line until it is opened, by a click on the line, a segment of
 * its document's bar (F33) or the block's address (F97); opened, its head, the heading's words,
 * folds it back to its line, and nothing else does on that page. A person's answer is not Pilot's,
 * so it opens the section for good, and Undo, which never gives an answer back to Pilot, leaves it
 * open. A held block's section (F31.7) is its block's line whether opened or not, the line over the
 * section once opened (block.tsx).
 */

import { createContext, useState } from 'react';
import { isAnswered, type Block, type BodyPart } from '@/hooks/use-timeline';

interface Sections {
  /** The blocks, by `<item>/<block>`, whose sections stand open. */
  opened: ReadonlySet<string>;
  open: (key: string) => void;
  close: (key: string) => void;
}

export const SectionsContext = createContext<Sections>({ opened: new Set(), open: () => undefined, close: () => undefined });

/** The sections opened on a page of its own; `at`, the block the page is at by `<item>/<block>`, opened as the page comes to it. */
export function useSections(at: string | null): Sections {
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  // The address last come to: it opens its section once, so that a section folded back there stays folded.
  const [came, setCame] = useState<string | null>(null);
  // In the render that brings it, so the block is drawn by the time the page goes to it.
  if (at !== came) {
    setCame(at);
    if (at !== null && !opened.has(at)) setOpened(new Set([...opened, at]));
  }
  const open = (key: string) => setOpened((current) => (current.has(key) ? current : new Set([...current, key])));
  const close = (key: string) => setOpened((current) => new Set([...current].filter((each) => each !== key)));
  return { opened, open, close };
}

/** Whether the block's section collapses while it is not opened: its own section, answered, its answer Pilot's. */
export const isSettled = (block: Block) => block.section !== null && block.by?.kind === 'agent' && isAnswered(block);

/** How a block's section is drawn: its line, collapsed; opened under its head; its held block's line; or as it is. */
export type Fold = 'collapsed' | 'opened' | 'held' | null;

/**
 * What a document's body draws: a part as it is, its heading dropped where an opened section's
 * head stands for it; an opened section's head before its first part; the blocks of consecutive
 * collapsed sections, each its line; or a held block with the parts of its own section, in their
 * order, the block among them.
 */
type Piece =
  | { type: 'part'; part: BodyPart; index: number; headed: boolean }
  | { type: 'head'; block: Block }
  | { type: 'settled'; blocks: Block[] }
  | { type: 'held'; block: Block; section: BodyPart[] };

/**
 * The body's pieces, every part of a collapsed section standing in its block's line, every part of
 * a held block's section in its block's piece, and an opened section's parts under its head.
 */
export function piecesOf(body: BodyPart[], foldOf: (block: Block) => Fold): Piece[] {
  const blocks = new Map(body.flatMap((part) => (part.type === 'block' ? [[part.block.id, part.block] as const] : [])));
  const fold = (owner: string | null) => {
    const block = owner === null ? undefined : blocks.get(owner);
    return block === undefined ? null : { block, fold: foldOf(block) };
  };
  const sections = new Map<string, BodyPart[]>();
  const headed = new Set<string>();
  const pieces: Piece[] = [];
  body.forEach((part, index) => {
    const owner = part.type === 'prose' ? part.section : part.block.section === null ? null : part.block.id;
    const own = part.type === 'block' ? { block: part.block, fold: foldOf(part.block) } : fold(owner);
    if (own?.fold === 'held') {
      // A section's parts and its block stand together: the block's piece takes them all.
      const key = own.block.id;
      const section = sections.get(key) ?? [];
      sections.set(key, section);
      section.push(part);
      if (part.type === 'block') pieces.push({ type: 'held', block: part.block, section });
      return;
    }
    if (own?.fold === 'opened' && owner !== null) {
      const first = !headed.has(owner);
      if (first) {
        headed.add(owner);
        pieces.push({ type: 'head', block: own.block });
      }
      pieces.push({ type: 'part', part, index, headed: first && part.type === 'prose' });
      return;
    }
    if (own?.fold !== 'collapsed' || owner === null) {
      pieces.push({ type: 'part', part, index, headed: false });
      return;
    }
    // A section's parts and its block stand together: its line goes once, in its block's place.
    if (part.type === 'prose') return;
    const last = pieces.at(-1);
    if (last?.type === 'settled') last.blocks.push(own.block);
    else pieces.push({ type: 'settled', blocks: [own.block] });
  });
  return pieces;
}

/** A section's first part's words under its heading, its first line. */
export function underHeading(markdown: string): string {
  const end = markdown.indexOf('\n');
  return end === -1 ? '' : markdown.slice(end + 1);
}

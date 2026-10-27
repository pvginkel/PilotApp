/**
 * Quote tags (F38.3; `database.md` decision 62): `<quoted_item id="…">…</quoted_item id="…">`,
 * `<quoted_block id="…/…">…</quoted_block id="…">` and `<quoted_path path="…">…</quoted_path
 * path="…">`, the closing tag repeating the attribute. A path is the handbook's, `handbook.md`, the
 * project document's, `project.md`, or an attachment's, `attachments/<batch>/<filename>`, whose
 * filename keeps the slashes of a folder it came in; a tag naming any other path is no quote. Every
 * screen that renders Markdown draws a quote as a chip wherever it stands (F39.3), except inside
 * code, or behind a backslash escape, where it shows as written.
 */

import remarkGfm from 'remark-gfm';
import remarkParse from 'remark-parse';
import { unified } from 'unified';

export interface QuoteRef {
  kind: 'item' | 'block' | 'path';
  /** An item's id, a block's `<item id>/<local id>`, or a path in the project's folder. */
  id: string;
  label: string;
}

const TAG =
  /<quoted_(item|block) id="([^"]+)">([\s\S]*?)<\/quoted_\1 id="\2">|<quoted_path path="(handbook\.md|project\.md|attachments\/[1-9][0-9]*(?:\/(?!\.{1,2}(?:\/|"))[^"/]+)+)">([\s\S]*?)<\/quoted_path path="\4">/g;

const labelOf = (body: string) => body.trim().split('\n')[0]!.slice(0, 120);

export const QUOTE_SCHEME = 'pilot-quote:';

// The parser `Markdown` draws with, react-markdown's with remark-gfm: what it reads as code is what
// shows as code.
const parser = unified().use(remarkParse).use(remarkGfm);

interface MarkdownNode {
  type: string;
  position?: { start: { offset?: number }; end: { offset?: number } };
  children?: MarkdownNode[];
}

/**
 * Where a quote tag is not one, as the text's Markdown reads: its code, spans and blocks, and its
 * raw HTML, whose text shows as written, all but a tag that starts it.
 */
function asWritten(text: string): (offset: number) => boolean {
  const ranges: [number, number][] = [];
  const walk = (node: MarkdownNode) => {
    if (node.type === 'code' || node.type === 'inlineCode' || node.type === 'html') {
      ranges.push([node.position!.start.offset!, node.position!.end.offset!]);
    } else node.children?.forEach(walk);
  };
  walk(parser.parse(text));
  return (offset) => ranges.some(([start, end]) => start < offset && offset < end);
}

/** Whether the character at an offset is behind a Markdown backslash escape: an odd run of backslashes before it. */
function escaped(text: string, offset: number): boolean {
  let start = offset;
  while (start > 0 && text[start - 1] === '\\') start -= 1;
  return (offset - start) % 2 === 1;
}

interface Quoted {
  /** The Markdown, each quote a link the renderer turns into a chip. */
  markdown: string;
  /** Where an offset of the text is in the Markdown: one inside a quote's tag, at its link's start. */
  at: (offset: number) => number;
}

/** The text's Markdown with each quote as a link the renderer turns into a chip. */
export function quotesToLinks(text: string): Quoted {
  if (!text.includes('<quoted_')) return { markdown: text, at: (offset) => offset };
  const written = asWritten(text);
  const cuts: { from: number; to: number; start: number; link: string }[] = [];
  let markdown = '';
  let last = 0;
  TAG.lastIndex = 0;
  for (let match = TAG.exec(text); match !== null; match = TAG.exec(text)) {
    if (written(match.index) || escaped(text, match.index)) {
      // A tag in code or escaped, or what follows it, can still hold one that is not.
      TAG.lastIndex = match.index + 1;
      continue;
    }
    const [all, kind, id, body, path, pathBody] = match;
    const label = labelOf(body ?? pathBody!).replace(/[[\]\\]/g, '\\$&');
    const href = path === undefined ? `${kind}/${encodeURIComponent(id!)}` : `path/${encodeURIComponent(path)}`;
    const link = `[${label}](${QUOTE_SCHEME}${href})`;
    markdown += text.slice(last, match.index);
    cuts.push({ from: match.index, to: match.index + all.length, start: markdown.length, link });
    markdown += link;
    last = match.index + all.length;
  }
  markdown += text.slice(last);
  const at = (offset: number) => {
    let index = cuts.length - 1;
    while (index >= 0 && cuts[index]!.from > offset) index -= 1;
    if (index < 0) return offset;
    const cut = cuts[index]!;
    return offset < cut.to ? cut.start : cut.start + cut.link.length + offset - cut.to;
  };
  return { markdown, at };
}

export type QuotePart = { type: 'text'; text: string } | { type: 'quote'; quote: QuoteRef };

/** A text that is not Markdown, a person's message, as its words and its quotes in their order. */
export function splitQuotes(text: string): QuotePart[] {
  const parts: QuotePart[] = [];
  let last = 0;
  TAG.lastIndex = 0;
  for (let match = TAG.exec(text); match !== null; match = TAG.exec(text)) {
    const [all, kind, id, body, path, pathBody] = match;
    if (match.index > last) parts.push({ type: 'text', text: text.slice(last, match.index) });
    const quote: QuoteRef =
      path === undefined
        ? { kind: kind as 'item' | 'block', id: id!, label: labelOf(body!) }
        : { kind: 'path', id: path, label: labelOf(pathBody!) };
    parts.push({ type: 'quote', quote });
    last = match.index + all.length;
  }
  if (last < text.length) parts.push({ type: 'text', text: text.slice(last) });
  return parts;
}

/** The tag a person's message carries for a quote, its label between the tags. */
export function quoteTag({ kind, id, label }: QuoteRef): string {
  const attribute = kind === 'path' ? `path="${id}"` : `id="${id}"`;
  return `<quoted_${kind} ${attribute}>${label}</quoted_${kind} ${attribute}>`;
}

export function parseQuoteHref(href: string): QuoteRef | null {
  if (!href.startsWith(QUOTE_SCHEME)) return null;
  const rest = href.slice(QUOTE_SCHEME.length);
  const slash = rest.indexOf('/');
  const kind = rest.slice(0, slash);
  if (kind !== 'item' && kind !== 'block' && kind !== 'path') return null;
  return { kind, id: decodeURIComponent(rest.slice(slash + 1)), label: '' };
}

const OPENINGS = ['<quoted_item id="', '<quoted_block id="', '<quoted_path path="'];

/** Whether a text from a `<` on is a quote tag still arriving: its opening tag under way, or its closing tag not yet come. */
function arriving(rest: string): boolean {
  const opening = OPENINGS.find((each) => rest.startsWith(each));
  if (opening === undefined) return OPENINGS.some((each) => each.startsWith(rest));
  const quote = rest.indexOf('"', opening.length);
  if (quote < 0 || quote + 1 === rest.length) return true;
  if (rest[quote + 1] !== '>') return false;
  return !rest.includes(`</${opening.slice(1)}${rest.slice(opening.length, quote)}">`, quote + 2);
}

/**
 * A streamed text cut before a quote tag still arriving: the chip shows once its closing tag has
 * come, and nothing of the tag shows before. A tag in code is never cut: it shows as written.
 */
export function cutOpenQuote(text: string): string {
  const starts: number[] = [];
  for (let at = text.indexOf('<quoted_'); at >= 0; at = text.indexOf('<quoted_', at + 1)) starts.push(at);
  // A tag's first characters at the very end: `<`, `<quo`.
  const tail = /<[a-z_]*$/.exec(text);
  if (tail !== null && tail.index !== starts.at(-1)) starts.push(tail.index);
  const cut = starts.filter((at) => arriving(text.slice(at)));
  if (cut.length === 0) return text;
  const written = asWritten(text);
  const at = cut.find((each) => !written(each));
  return at === undefined ? text : text.slice(0, at);
}

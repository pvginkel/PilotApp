/**
 * The phantom's new text fading in (decision 1). Every text delta is its own span, so the text
 * already shown keeps its place each time the Markdown re-renders, and only the deltas of the
 * last moment carry the fade. A block the Markdown rebuilds mid-stream (a line that becomes a
 * list item or a table once its marker comes) so does not flash the text it already showed.
 *
 * The split is a rehype plugin on the source positions react-markdown keeps: a text node is cut
 * where a delta starts. A quote's chip keeps its label whole and comes with the delta that closed
 * its tag; a text node whose source is not its text (an escape) goes whole with the delta it
 * starts in.
 */

import { cutOpenQuote, quotesToLinks, QUOTE_SCHEME } from '@/lib/chat/quotes';
import type { Delta } from '@/lib/chat/stream-state';

/** How long a delta fades in (`.delta-fresh` in index.css). */
const FADE_MS = 300;
/** A delta stays fresh a little past its fade, so that no re-render cuts the fade short. */
const FRESH_MS = FADE_MS + 100;

export interface DeltaMarks {
  /** Where each delta starts in the Markdown source, ascending. */
  starts: number[];
  /** Whether each is still fading in. */
  fresh: boolean[];
}

/**
 * The deltas of the text shown (the phantom's text cut before an open quote tag), placed in the
 * Markdown source, which has each quote as a link. Fresh is measured against the latest delta,
 * not the clock, so it stays a function of the stream.
 */
export function deltaMarks(shown: string, deltas: Delta[]): DeltaMarks {
  const latest = deltas.at(-1)?.t ?? 0;
  const quoted = shown.includes('<quoted_');
  const starts: number[] = [];
  const fresh: boolean[] = [];
  for (const d of deltas) {
    if (d.at >= shown.length) break;
    starts.push(quoted ? quotesToLinks(cutOpenQuote(shown.slice(0, d.at))).length : d.at);
    fresh.push(latest - d.t < FRESH_MS);
  }
  return { starts, fresh };
}

// The few hast shapes the plugin reads: react-markdown's tree, without a dependency on its types.
interface Point {
  offset?: number;
}
interface Position {
  start: Point;
  end: Point;
}
interface HText {
  type: 'text';
  value: string;
  position?: Position;
}
interface HElement {
  type: 'element';
  tagName: string;
  properties: Record<string, unknown>;
  children: HNode[];
  position?: Position;
}
type HNode = HText | HElement | { type: 'root' | 'comment' | 'doctype' | 'raw'; children?: HNode[]; position?: Position };

export function rehypeDeltas(marks: DeltaMarks) {
  return (tree: HNode, file: { value?: unknown }) => {
    const source = typeof file.value === 'string' ? file.value : '';
    const { starts } = marks;

    // The delta a source offset is in: the last to start at or before it; -1 before the first.
    const deltaAt = (offset: number) => {
      let lo = 0;
      let hi = starts.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (starts[mid]! <= offset) lo = mid + 1;
        else hi = mid;
      }
      return lo - 1;
    };
    const span = (d: number, children: HNode[]): HElement => ({
      type: 'element',
      tagName: 'span',
      properties: marks.fresh[d] ? { className: ['delta-fresh'] } : {},
      children,
    });
    const whole = (node: HNode, offset: number | undefined): HNode => {
      const d = offset == null ? -1 : deltaAt(offset);
      return d < 0 ? node : span(d, [node]);
    };

    // Where the text's first character is in the source. A fenced block's text has no position
    // of its own, so its `code` element's stands in, and ends in a newline its source may not
    // have yet; inline code's sits between its backticks. The newlines between blocks have none,
    // and stay as they are.
    const startOf = (node: HText, parent: HNode): number | null => {
      const pos = node.position ?? (parent.type === 'element' && parent.tagName === 'code' ? parent.position : undefined);
      const s = pos?.start.offset;
      const e = pos?.end.offset;
      if (s == null || e == null) return null;
      if (e - s === node.value.length) return s;
      const slice = source.slice(s, e);
      const i = slice.indexOf(node.value);
      if (i >= 0) return s + i;
      const bare = node.value.replace(/\n$/, '');
      const j = bare ? slice.indexOf(bare) : -1;
      return j >= 0 ? s + j : null;
    };

    const split = (node: HText, parent: HNode): HNode[] => {
      const k = startOf(node, parent);
      if (k == null) return [whole(node, node.position?.start.offset)];
      const v = node.value;
      const pieces: HNode[] = [];
      let d = deltaAt(k);
      let i = 0;
      while (i < v.length) {
        const next = starts[d + 1];
        const end = next === undefined ? v.length : Math.min(v.length, Math.max(i, next - k));
        if (end > i) {
          const text: HText = { type: 'text', value: v.slice(i, end) };
          pieces.push(d < 0 ? text : span(d, [text]));
        }
        i = end;
        d++;
      }
      return pieces;
    };

    const walk = (parent: HNode) => {
      if (parent.type === 'text' || !parent.children) return;
      parent.children = parent.children.flatMap((node): HNode[] => {
        if (node.type === 'text') return split(node, parent);
        if (node.type === 'element') {
          const href = node.properties.href;
          if (node.tagName === 'a' && typeof href === 'string' && href.startsWith(QUOTE_SCHEME)) {
            const end = node.position?.end.offset;
            return [whole(node, end == null ? undefined : end - 1)];
          }
        }
        walk(node);
        return [node];
      });
    };
    walk(tree);
  };
}

/**
 * Quote tags (F38.3): `<quoted_item id="…">…</quoted_item id="…">` and `<quoted_block id="…/…">…
 * </quoted_block id="…">`, the closing tag repeating the attributes. The view renders each as a
 * chip wherever it stands, in a person's message and in Pilot's reply alike (F39.3).
 */

export interface QuoteRef {
  kind: 'item' | 'block';
  /** An item's id, or a block's `<item id>/<local id>`. */
  id: string;
  label: string;
}

const TAG = /<quoted_(item|block) id="([^"]+)">([\s\S]*?)<\/quoted_\1 id="\2">/g;

const labelOf = (body: string) => body.trim().split('\n')[0]!.slice(0, 120);

export const QUOTE_SCHEME = 'pilot-quote:';

/** Markdown with each quote as a link the renderer turns into a chip. */
export function quotesToLinks(text: string): string {
  return text.replace(TAG, (_all, kind: string, id: string, body: string) => {
    const label = labelOf(body).replace(/[[\]\\]/g, '\\$&');
    return `[${label}](${QUOTE_SCHEME}${kind}/${encodeURIComponent(id)})`;
  });
}

export function parseQuoteHref(href: string): QuoteRef | null {
  if (!href.startsWith(QUOTE_SCHEME)) return null;
  const rest = href.slice(QUOTE_SCHEME.length);
  const slash = rest.indexOf('/');
  const kind = rest.slice(0, slash);
  if (kind !== 'item' && kind !== 'block') return null;
  return { kind, id: decodeURIComponent(rest.slice(slash + 1)), label: '' };
}

/**
 * A streamed text cut before a quote tag still arriving: the chip shows once its closing tag
 * has come, and nothing of the tag shows before.
 */
export function cutOpenQuote(text: string): string {
  const open = text.lastIndexOf('<quoted_');
  if (open >= 0) {
    const closed = TAG.test(text.slice(open));
    TAG.lastIndex = 0;
    if (!closed) return text.slice(0, open);
  }
  // A tag's first characters at the very end: `<`, `<quo`.
  const tail = /<[a-z_]*$/.exec(text);
  if (tail && '<quoted_'.startsWith(tail[0].slice(0, 8))) return text.slice(0, tail.index);
  return text;
}

/**
 * Markdown as every screen draws it (F29.1): GFM, inside `.prose`. Ticket ids, repos and
 * environments in its text link as they do in all of the record's words (F91, F93), except in code
 * and inside a link; every link opens in a new tab. A quote tag is a chip that goes to what it
 * quotes (F39.3), except in code, where it shows as written, and a streamed text's new deltas fade
 * in (the chat's decision 1; delta-fade.ts). A heading's words stand alone, inline, as the heading
 * shows them. A text that links only to the documents it names by path, as a draft does (F47.3),
 * draws each link through its own component, and links nothing else.
 */

import { memo, useMemo, type ComponentType, type ReactNode } from 'react';
import ReactMarkdown, { defaultUrlTransform, type Components, type Options } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ElementContent, Root } from 'hast';
import { rehypeDeltas, type DeltaMarks } from '@/components/chat/delta-fade';
import { QuoteChip } from '@/components/chat/quote-chip';
import { NestedLink } from '@/components/shared/linked-text';
import { useLinker } from '@/components/shared/links-context';
import { parseQuoteHref, QUOTE_SCHEME, quotesToLinks } from '@/lib/chat/quotes';
import type { Linker } from '@/lib/links';
import { cn } from '@/lib/utils';

/** GFM, but only a double `~` strikes text out: a single one, as in `[!-~]+`, stays as written (P-139). */
const remarkPlugins: Options['remarkPlugins'] = [[remarkGfm, { singleTilde: false }]];

const UNLINKED = new Set(['a', 'code', 'pre']);

function linkIn(children: ElementContent[], link: Linker): ElementContent[] {
  return children.flatMap((child): ElementContent[] => {
    if (child.type === 'text') {
      return link(child.value).map((piece) =>
        piece.link === undefined
          ? { type: 'text', value: piece.text }
          : {
              type: 'element',
              tagName: 'a',
              properties: { className: ['mention'], href: piece.link.href, title: piece.link.title },
              children: [{ type: 'text', value: piece.text }],
            },
      );
    }
    if (child.type === 'element' && !UNLINKED.has(child.tagName)) child.children = linkIn(child.children, link);
    return [child];
  });
}

function rehypeLinks(link: Linker) {
  return (tree: Root) => {
    for (const child of tree.children) {
      if (child.type === 'element') child.children = linkIn(child.children, link);
    }
  };
}

const components: Components = {
  a: ({ href, title, className, children }) => {
    const quote = href === undefined ? null : parseQuoteHref(href);
    if (quote) return <QuoteChip quote={{ ...quote, label: String(children) }} label={children} />;
    return (
      <a href={href} title={title} className={className} target="_blank" rel="noreferrer">
        {children}
      </a>
    );
  },
};

const urlTransform = (url: string) => (url.startsWith(QUOTE_SCHEME) ? url : defaultUrlTransform(url));

const nestedComponents: Components = {
  a: ({ href, title, children }) => (
    // A link's address is never unset: the Markdown that makes the link gives it one.
    <NestedLink href={href!} title={title}>
      {children}
    </NestedLink>
  ),
};

/**
 * A heading's inline Markdown without the heading around it, inside a button: emphasis, code and
 * links as the heading shows them, each link opening as one nested in a button does, and nothing
 * its words would make outside a heading, such as a list.
 */
export const HeadingWords = memo(function HeadingWords({ text }: { text: string }) {
  const link = useLinker();
  const rehypePlugins = useMemo((): Options['rehypePlugins'] => [[rehypeLinks, link]], [link]);
  // Read as a heading's, then unwrapped. The closing `#` is the one a heading drops, so that a `#`
  // ending the words stays in them.
  const source = `# ${text} #`;
  return (
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      components={nestedComponents}
      disallowedElements={['h1']}
      unwrapDisallowed
    >
      {source}
    </ReactMarkdown>
  );
});

/** A link of a text that links only to documents: its address as written, and its words. */
export type DocumentLinkProps = { href: string; children: ReactNode };

interface MarkdownProps {
  text: string;
  className?: string;
  /** A streamed text's deltas, placed in the text, its new text fading in. */
  deltas?: DeltaMarks;
  /** Draws each link, the text linking nothing else: no ticket id, repo or environment. */
  documentLink?: ComponentType<DocumentLinkProps>;
}

export const Markdown = memo(function Markdown({ text, className, deltas, documentLink: DocumentLink }: MarkdownProps) {
  const link = useLinker();
  const quoted = useMemo(() => quotesToLinks(text), [text]);
  // The deltas split the text by its source positions, which the links' pieces do not keep.
  const rehypePlugins = useMemo((): Options['rehypePlugins'] => {
    const plugins: NonNullable<Options['rehypePlugins']> = [];
    if (deltas !== undefined) plugins.push([rehypeDeltas, { starts: deltas.starts.map(quoted.at), fresh: deltas.fresh }]);
    if (DocumentLink === undefined) plugins.push([rehypeLinks, link]);
    return plugins;
  }, [deltas, link, quoted, DocumentLink]);
  const drawn = useMemo(
    (): Components =>
      DocumentLink === undefined
        ? components
        : {
            a: ({ href, children }) => {
              const quote = href === undefined ? null : parseQuoteHref(href);
              if (quote) return <QuoteChip quote={{ ...quote, label: String(children) }} label={children} />;
              // A link's address is never unset: the Markdown that makes the link gives it one.
              return <DocumentLink href={href!}>{children}</DocumentLink>;
            },
          },
    [DocumentLink],
  );
  return (
    <div className={cn('prose', className)}>
      <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={drawn} urlTransform={urlTransform}>
        {quoted.markdown}
      </ReactMarkdown>
    </div>
  );
});

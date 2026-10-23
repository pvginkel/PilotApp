/**
 * Markdown as every screen draws it (F29.1): GFM, inside `.prose`. Ticket ids, repos and
 * environments in its text link as they do in all of the record's words (F91, F93), except in code
 * and inside a link; every link opens in a new tab. A heading's words stand alone, inline, as the
 * heading shows them.
 */

import { memo, useMemo } from 'react';
import ReactMarkdown, { type Components, type Options } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ElementContent, Root } from 'hast';
import { NestedLink } from '@/components/shared/linked-text';
import { useLinker } from '@/components/shared/links-context';
import type { Linker } from '@/lib/links';

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
  a: ({ href, title, className, children }) => (
    <a href={href} title={title} className={className} target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
};

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
      remarkPlugins={[remarkGfm]}
      rehypePlugins={rehypePlugins}
      components={nestedComponents}
      disallowedElements={['h1']}
      unwrapDisallowed
    >
      {source}
    </ReactMarkdown>
  );
});

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  const link = useLinker();
  const rehypePlugins = useMemo((): Options['rehypePlugins'] => [[rehypeLinks, link]], [link]);
  return (
    <div className="prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={rehypePlugins} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
});

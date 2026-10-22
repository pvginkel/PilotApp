/**
 * Text as every screen shows it (F91, F93): ticket ids, repos and environments link where they
 * stand, in the colour of the text around them, underlined under the mouse. Inside a link or a
 * button, where a link cannot nest, each is a span that opens it on a click or on Enter.
 */

import { useMemo, type ReactNode, type SyntheticEvent } from 'react';
import { LinksContext, useLinker } from '@/components/shared/links-context';
import { useGetLinks } from '@/lib/api/generated/hooks';
import { linker, unlinked } from '@/lib/links';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

/** Reads what links once for every text under it; until then, text shows unlinked. */
export function LinksProvider({ children }: { children: ReactNode }) {
  const query = useGetLinks();
  useUiStateInstrumentation('links', { isLoading: query.isLoading, error: query.error });
  const link = useMemo(() => (query.data === undefined ? unlinked : linker(query.data)), [query.data]);
  return <LinksContext.Provider value={link}>{children}</LinksContext.Provider>;
}

interface LinkedTextProps {
  text: string;
  /** The text stands inside a link or a button. */
  nested?: boolean;
}

export function LinkedText({ text, nested = false }: LinkedTextProps) {
  const link = useLinker();
  return link(text).map((piece, index) => {
    if (piece.link === undefined) return piece.text;
    const { href, title } = piece.link;
    return nested ? (
      <NestedLink key={index} href={href} title={title} text={piece.text} />
    ) : (
      <a key={index} className="mention" href={href} title={title} target="_blank" rel="noreferrer">
        {piece.text}
      </a>
    );
  });
}

function NestedLink({ href, title, text }: { href: string; title: string; text: string }) {
  const open = (event: SyntheticEvent) => {
    // The link or the button around it must not act too: the click bubbles to it, and so does
    // Enter, which a link turns into a click of its own.
    event.preventDefault();
    event.stopPropagation();
    window.open(href, '_blank', 'noreferrer');
  };
  return (
    <span
      className="mention"
      role="link"
      tabIndex={0}
      title={title}
      data-href={href}
      onClick={open}
      onKeyDown={(event) => event.key === 'Enter' && open(event)}
    >
      {text}
    </span>
  );
}

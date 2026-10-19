/**
 * What links in text (F91, F93): a ticket id by the deployment's pattern and URL template, a repo
 * written pvginkel/Name to GitHub, and an environment to KubeCoder's Open, by its id's form or by
 * the name of one of the record's environments. A setting left unset leaves its text unlinked.
 */

import type { components } from '@/lib/api/generated/types';

type LinkSettings = components['schemas']['LinksResponseSchema.d9d9a05'];

interface Link {
  href: string;
  title: string;
}

interface TextPiece {
  text: string;
  link?: Link;
}

/** Text cut into its plain stretches and its links, in order. */
export type Linker = (text: string) => TextPiece[];

export const unlinked: Linker = (text) => [{ text }];

/** A kind of link: what it matches in text, and where what it matched goes. */
interface Kind {
  pattern: string;
  link: (found: string) => Link;
}

const REPO = String.raw`\bpvginkel\/[A-Za-z0-9_-]+`;
const ENVIRONMENT_ID = String.raw`\bpvginkel-[a-z0-9-]+-[0-9a-f]{6}\b`;

const quote = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * A name ending in a number (Ansible-1) links wherever it stands; one without (Notifications)
 * names its project too, so it links only as "the Notifications environment".
 */
const environmentName = (name: string) =>
  /-\d+$/.test(name) ? String.raw`\b${quote(name)}\b` : String.raw`\b${quote(name)}(?= environments?\b)`;

/** The ticket id pattern is the backend's, in Python `re` syntax; its default reads the same here. */
export function linker(settings: LinkSettings): Linker {
  const { ticket_url_template: ticketUrl, environment_link_base_url: base } = settings;
  const kinds: Kind[] = [];
  if (ticketUrl !== null) {
    kinds.push({
      pattern: String.raw`\b(?:${settings.ticket_id_pattern})\b`,
      link: (id) => ({ href: ticketUrl.replaceAll('{id}', encodeURIComponent(id)), title: `Open ${id} in the tracker` }),
    });
  }
  kinds.push({ pattern: REPO, link: (repo) => ({ href: `https://github.com/${repo}`, title: `Open ${repo} on GitHub` }) });
  if (base !== null) {
    const open = (id: string, found: string) => ({
      href: `${base}/environments/${encodeURIComponent(id)}/ssh/open`,
      title: `Open ${found} in VS Code`,
    });
    kinds.push({ pattern: ENVIRONMENT_ID, link: (id) => open(id, id) });
    // The longest name first: of Lab-1 and Lab-1-2, both matching at "Lab-1-2", the longer wins.
    for (const { id, name } of [...settings.environments].sort((a, b) => b.name.length - a.name.length)) {
      kinds.push({ pattern: environmentName(name), link: (found) => open(id, found) });
    }
  }
  // Each kind its own named group, so a group in the ticket id pattern shifts nothing.
  const pattern = new RegExp(kinds.map((kind, index) => `(?<k${index}>${kind.pattern})`).join('|'), 'g');

  return (text) => {
    const pieces: TextPiece[] = [];
    let at = 0;
    for (const match of text.matchAll(pattern)) {
      const kind = kinds.find((_, index) => match.groups![`k${index}`] !== undefined)!;
      if (match.index > at) pieces.push({ text: text.slice(at, match.index) });
      pieces.push({ text: match[0], link: kind.link(match[0]) });
      at = match.index + match[0].length;
    }
    if (at < text.length) pieces.push({ text: text.slice(at) });
    return pieces;
  };
}

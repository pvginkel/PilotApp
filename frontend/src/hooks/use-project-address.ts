/**
 * A project's address, `/projects/<address>` (H3): its slug once Create project has given it one,
 * else `draft-<number>`, the name of its folder in the store's tree, which still names it after
 * Create; and its id names it too. An address names its one project for good: a slug is set once,
 * a draft's number is never handed out again, and no slug starts `draft-` or reads as an id. The
 * API and what the browser keeps name a project by its id, which its address resolves to: an id's
 * as it stands, an address a project list's read holds from that list, any other by
 * GET /api/projects/lookup, read once.
 */

import { createContext, useContext } from 'react';
import type { Query, QueryClient } from '@tanstack/react-query';
import { useParams } from '@tanstack/react-router';
import { useGetProjects, useGetProjectsLookup } from '@/lib/api/generated/hooks';

/** An id as the API writes it; another spelling of one is looked up, which answers it so. */
const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** The project at the address, as its lookup answers it. */
const lookupOf = (address: string) => ['getProjectsLookup', { query: { address } }];

/** That the project `id` is at `address`, as its lookup would answer, so that the page has it without asking. */
export function knowAt(queryClient: QueryClient, address: string, id: string): void {
  queryClient.setQueryData(lookupOf(address), { id, address });
}

/** The id of the project at the address; undefined for no address, and until it is known. */
export function useProjectIdAt(address: string | undefined): string | undefined {
  const id = address !== undefined && ID.test(address);
  // The lists as the side column reads them, read for this by no one.
  const lists = [
    useGetProjects({ query: { archived: false } }, { enabled: false }).data,
    useGetProjects({ query: { archived: true } }, { enabled: false }).data,
  ];
  const tab = id ? undefined : lists.flatMap((list) => list?.projects ?? []).find((each) => each.address === address);
  const { data } = useGetProjectsLookup(
    { query: { address } },
    {
      // Read once: an answer is never read again, not on a write's invalidation of every query.
      enabled: (query: Query<unknown, unknown>) => address !== undefined && !id && tab === undefined && query.state.data === undefined,
    },
  );
  return id ? address : (tab?.id ?? data?.id);
}

/** The id of the project on screen, at its address or one under it; undefined elsewhere, and until it is known. */
export function useProjectOnScreen(): string | undefined {
  return useProjectIdAt(useParams({ strict: false, select: (params) => params.address }));
}

/** The project its route shows: its id, and the address its pages' URLs take, the one it is at. */
interface ShownProject {
  id: string;
  address: string;
}

export const ShownProjectContext = createContext<ShownProject | null>(null);

export function useShownProject(): ShownProject {
  const shown = useContext(ShownProjectContext);
  if (shown === null) throw new Error('useShownProject() is read only under the project route');
  return shown;
}

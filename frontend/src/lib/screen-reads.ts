/**
 * What a project's screens read before the router swaps one in: a project's head and its
 * timeline, or a draft's chats in the timeline's place; a document's tab its document, a card's
 * block its card's, the handbook's and the project document's their own. A route's loader reads
 * them into the page's cache, each under its generated hook's key, so that the router keeps the
 * screen showing until they are in, and the loading bar tells of a wait past 200 ms
 * (`loading-bar.tsx`); a project's tab reads its project's as the router preloads its route, on
 * hover or touch. What the cache holds stands, the screen reading it again. A read that fails
 * keeps its error in the cache, which the screen shows once swapped in. The page's first screen
 * waits for none: there is no screen to keep.
 */

import { isCard } from '@/components/timeline/document-state';
import { heldAt, knowAt } from '@/hooks/use-project-address';
import type { ProjectHead } from '@/hooks/use-projects';
import { toApiError } from '@/lib/api/api-error';
import { api } from '@/lib/api/generated/client';
import type { components } from '@/lib/api/generated/types';
import { queryClient } from '@/lib/query-client';

type Schemas = components['schemas'];

/** A screen shows: from the shell's first on, a route keeps the one showing while it reads. */
let shown = false;

export function screenShown(): void {
  shown = true;
}

/** A route's loader that reads `reads` before the router swaps its screen in, a stale match's again. */
export function readFirst<P>(reads: (params: P) => Promise<unknown>) {
  return {
    handler: async ({ params, preload }: { params: P; preload: boolean }) => {
      if (!shown && !preload) return;
      await reads(params).catch(() => undefined);
    },
    staleReloadMode: 'blocking' as const,
  };
}

/** A GET into the page's cache under its generated hook's key, read as the hook reads it, where the cache holds none. */
function cached<T>(hook: string, params: object, get: () => Promise<unknown>): Promise<T> {
  return queryClient.ensureQueryData<T>({
    queryKey: [hook, params],
    queryFn: async () => {
      const result = (await get()) as { data?: T; error?: unknown; response: Response };
      if (result.error) throw toApiError(result.error, result.response.status);
      return result.data!;
    },
  });
}

const projectParams = (project_id: string) => ({ path: { project_id } });

const headRead = (id: string) =>
  cached<ProjectHead>('getProjectsByProjectId', projectParams(id), () => api.GET('/api/projects/{project_id}', { params: projectParams(id) }));

const timelineRead = (id: string) =>
  cached<Schemas['TimelineSchema.1fdd8ae']>('getProjectsTimelineByProjectId', projectParams(id), () =>
    api.GET('/api/projects/{project_id}/timeline', { params: projectParams(id) }),
  );

const chatsRead = (id: string) =>
  cached('getProjectsChatsByProjectId', projectParams(id), () => api.GET('/api/projects/{project_id}/chats', { params: projectParams(id) }));

const documentRead = (item_id: string) =>
  cached('getItemsDocumentByItemId', { path: { item_id } }, () => api.GET('/api/items/{item_id}/document', { params: { path: { item_id } } }));

/** The project lists as the side column read them. */
const lists = () =>
  [false, true].map((archived) => queryClient.getQueryData<Schemas['ProjectListResponseSchema.e86ccd6']>(['getProjects', { query: { archived } }]));

/** The id of the project at the address: as the page holds it, else looked up, as `useProjectIdAt` reads it. */
async function idAt(address: string): Promise<string> {
  const query = { query: { address } };
  const id =
    heldAt(address, lists()) ??
    (await cached<Schemas['ProjectAddressSchema.e86ccd6']>('getProjectsLookup', query, () => api.GET('/api/projects/lookup', { params: query }))).id;
  knowAt(address, id);
  return id;
}

/** A project's screen: its head, and its timeline, or a draft's chats, read beside the head where the page knows which. */
export async function readProject(address: string): Promise<void> {
  const id = await idAt(address);
  const head = headRead(id);
  const state =
    queryClient.getQueryData<ProjectHead>(['getProjectsByProjectId', projectParams(id)])?.state ??
    lists()
      .flatMap((list) => list?.projects ?? [])
      .find((each) => each.id === id)?.state ??
    (await head).state;
  await Promise.all([head, state === 'draft' ? chatsRead(id) : timelineRead(id)]);
}

/** A document's tab: its document. */
export const readDocument = (documentId: string): Promise<unknown> => documentRead(documentId);

/** A block's address: where its item is a card, the card's document, which opens at the block. */
export async function readBlock(address: string, itemId: string): Promise<void> {
  const item = (await timelineRead(await idAt(address))).items.find((each) => each.id === itemId);
  if (item !== undefined && isCard(item)) await documentRead(itemId);
}

/** The handbook's tab. */
export async function readHandbook(address: string): Promise<unknown> {
  const id = await idAt(address);
  return cached('getProjectsHandbookByProjectId', projectParams(id), () => api.GET('/api/projects/{project_id}/handbook', { params: projectParams(id) }));
}

/** The project document's tab. */
export async function readProjectDocument(address: string): Promise<unknown> {
  const id = await idAt(address);
  return cached('getProjectsDraftByProjectId', projectParams(id), () => api.GET('/api/projects/{project_id}/draft', { params: projectParams(id) }));
}

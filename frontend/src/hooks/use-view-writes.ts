/**
 * The dashboard's writes on its views (F161.7): a view's star, the person's own (F155.2), and a
 * saved view's rename and remove, for everyone; Save view, a tab's state saved under a name, for
 * everyone, the tab taking it (F161.5). What went well is a toast, and what failed the
 * banner under the global toolbar alone (F160.8): each write's own failure replaces the query
 * client's toast every failed write has by default. A write reads again what it changed and no
 * more, never the figures, which the generated hooks' success would read again with every other
 * query.
 */

import { createContext, useContext } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/hooks/use-toast';
import { useViewTabMoves, viewRenamed } from '@/hooks/use-view-tabs';
import { toApiError } from '@/lib/api/api-error';
import { api } from '@/lib/api/client';
import { SENDER } from '@/lib/api/generated/hooks';
import { catalogueQuery, favouritesQuery, knowNormal, stateOf, type Catalogue, type Favourites, type SavedView } from '@/lib/dashboard/queries';

/** Shows what failed in the dashboard's banner: a write, or a read apart from the view's rows, with its Retry. */
export const Failures = createContext<((error: Error, retry?: () => void) => void) | null>(null);

const headers = { 'X-Sender': SENDER };

/** A rename refused as another saved view's name. */
export const isNameTaken = (error: Error) => (error as Error & { status?: number }).status === 409;

/** Changes the saved views the page holds, where it holds them. */
function useSavedViews() {
  const queryClient = useQueryClient();
  const stored = catalogueQuery('stored').queryKey;
  return (change: (views: SavedView[]) => SavedView[]) =>
    queryClient.setQueryData<Catalogue>(stored, (was) => (was?.saved_views == null ? was : { ...was, saved_views: change(was.saved_views) }));
}

export function useViewWrites() {
  const queryClient = useQueryClient();
  const fail = useContext(Failures)!;
  const { showSuccess } = useToast();
  const stored = catalogueQuery('stored').queryKey;
  const favourites = favouritesQuery().queryKey;
  const savedViews = useSavedViews();

  const star = useMutation({
    mutationFn: async ({ view, on }: { view: SavedView; on: boolean }) => {
      const options = { params: { path: { view_id: view.id } }, headers };
      const { error, response } = on
        ? await api.PUT('/api/dashboard/saved-views/{view_id}/star', options)
        : await api.DELETE('/api/dashboard/saved-views/{view_id}/star', options);
      if (error !== undefined) throw toApiError(error, response.status);
    },
    // Taken at once, a star added last in the order starred.
    onMutate: async ({ view, on }) => {
      await queryClient.cancelQueries({ queryKey: favourites });
      queryClient.setQueryData<Favourites>(favourites, (was) =>
        was === undefined ? was : { ...was, views: [...was.views.filter((id) => id !== view.id), ...(on ? [view.id] : [])] },
      );
    },
    onError: (error) => fail(error),
    onSettled: () => queryClient.invalidateQueries({ queryKey: favourites }),
  });

  const rename = useMutation({
    mutationFn: async ({ view, name }: { view: SavedView; name: string }) => {
      const { data, error, response } = await api.PATCH('/api/dashboard/saved-views/{view_id}', {
        params: { path: { view_id: view.id } },
        body: { name },
        headers,
      });
      if (error !== undefined) throw toApiError(error, response.status);
      return data;
    },
    onSuccess: (renamed, { view }) => {
      savedViews((views) => views.map((each) => (each.id === renamed.id ? renamed : each)));
      viewRenamed(renamed.id, renamed.name);
      showSuccess(`Renamed the view "${view.name}" to "${renamed.name}"`);
    },
    // A name taken is said under the field, which stays open; another failure reads the views again.
    onError: (error) => {
      if (isNameTaken(error)) return;
      fail(error);
      void queryClient.invalidateQueries({ queryKey: stored });
    },
  });

  const remove = useMutation({
    mutationFn: async (view: SavedView) => {
      const { error, response } = await api.DELETE('/api/dashboard/saved-views/{view_id}', { params: { path: { view_id: view.id } }, headers });
      if (error !== undefined) throw toApiError(error, response.status);
    },
    onSuccess: (_, view) => {
      savedViews((views) => views.filter((each) => each.id !== view.id));
      showSuccess(`Removed the view "${view.name}" for everyone`);
    },
    onError: (error) => {
      fail(error);
      void queryClient.invalidateQueries({ queryKey: stored });
    },
    // The stars on it go with it.
    onSettled: () => queryClient.invalidateQueries({ queryKey: favourites }),
  });

  return { star, rename, remove };
}

/**
 * Save view (F161.5): the state of the tab `tab`, its look-only parts with it, saved for everyone
 * under `name`, replacing the saved view of that name, a system view's staying beside it; the tab
 * takes the saved view, its name and the state it holds, which Reset goes back to.
 */
export function useSaveView() {
  const queryClient = useQueryClient();
  const fail = useContext(Failures)!;
  const { showSuccess } = useToast();
  const moves = useViewTabMoves();
  const savedViews = useSavedViews();
  return useMutation({
    mutationFn: async ({ name, state }: { tab: string; name: string; state: string }) => {
      const { data, error, response } = await api.POST('/api/dashboard/saved-views', { body: { name, state }, headers });
      if (error !== undefined) throw toApiError(error, response.status);
      return { ...data, made: response.status === 201 };
    },
    onSuccess: ({ view, notes, made }, { tab }) => {
      savedViews((views) => (views.some((each) => each.id === view.id) ? views.map((each) => (each.id === view.id ? view : each)) : [...views, view]));
      knowNormal(queryClient, view.address);
      moves.saved(tab, { id: view.id, name: view.name }, stateOf(view.address));
      showSuccess([made ? `Saved the view "${view.name}" for everyone` : `Replaced the saved view "${view.name}" for everyone`, ...notes].join('. '));
    },
    onError: (error) => fail(error),
  });
}

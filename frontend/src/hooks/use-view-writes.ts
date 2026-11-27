/**
 * The dashboard's writes on what it stores (F161.7, F162.6, F163.2): a view's star and a
 * dimension's in By's list or Color's, the person's own (F155.2), and a saved view's rename and
 * remove, for everyone; Save view, a tab's state saved under
 * a name, for everyone, the tab taking it (F161.5); a quick filter made and removed, for everyone,
 * the counts read again; a custom ratio made, changed and removed, for everyone (F163.6). What went
 * well is a toast, and what failed the
 * banner under the global toolbar alone (F160.8): each write's own failure replaces the query
 * client's toast every failed write has by default. A write reads again what it changed and no
 * more, the figures among it only where it changed them, where the generated hooks' success reads
 * again every query but the figures and the labels (`KEPT_FROM_WRITES`).
 */

import { createContext, useContext } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/hooks/use-toast';
import { useViewTabMoves, viewRenamed } from '@/hooks/use-view-tabs';
import { toApiError } from '@/lib/api/api-error';
import { api } from '@/lib/api/client';
import { SENDER } from '@/lib/api/generated/hooks';
import { namesRatio, withoutRatio } from '@/lib/dashboard/measures';
import {
  catalogueQuery,
  favouritesQuery,
  knowNormal,
  normalFormsChanged,
  quickFiltersChanged,
  ratioChanged,
  stateOf,
  type Catalogue,
  type CustomRatio,
  type Favourites,
  type QuickFilter,
  type SavedView,
} from '@/lib/dashboard/queries';
import { readState, StateFormError, writeState } from '@/lib/dashboard/state';
import type { components } from '@/lib/api/generated/types';

/** By's list or Color's, where a dimension is a favorite. */
type Menu = keyof Pick<Favourites, 'by' | 'color'>;

type RatioWrite = components['schemas']['CustomRatioWriteSchema.ddf95d6'];

/** Shows what failed in the dashboard's banner. */
export const WriteFailures = createContext<((error: Error) => void) | null>(null);

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
  const fail = useContext(WriteFailures)!;
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
    onError: fail,
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
 * A dimension starred in By's list or Color's (F155.2), the person's own: taken at once, last in
 * the order starred, the favorites read again after.
 */
export function useFavouriteWrites() {
  const queryClient = useQueryClient();
  const fail = useContext(WriteFailures)!;
  const favourites = favouritesQuery().queryKey;
  const favour = useMutation({
    mutationFn: async ({ menu, dimension, on }: { menu: Menu; dimension: string; on: boolean }) => {
      const { error, response } = on
        ? await api.POST('/api/dashboard/favourites/dimensions', { body: { menu, dimension }, headers })
        : await api.DELETE('/api/dashboard/favourites/dimensions', { params: { query: { menu, dimension } }, headers });
      if (error !== undefined) throw toApiError(error, response.status);
    },
    onMutate: async ({ menu, dimension, on }) => {
      await queryClient.cancelQueries({ queryKey: favourites });
      queryClient.setQueryData<Favourites>(favourites, (was) =>
        was === undefined ? was : { ...was, [menu]: [...was[menu].filter((key) => key !== dimension), ...(on ? [dimension] : [])] },
      );
    },
    onError: fail,
    onSettled: () => queryClient.invalidateQueries({ queryKey: favourites }),
  });
  return { favour };
}

/**
 * Save view (F161.5): the state of the tab `tab`, its look-only parts with it, saved for everyone
 * under `name`, replacing the saved view of that name, a system view's staying beside it; the tab
 * takes the saved view, its name and the state it holds, which Reset goes back to.
 */
export function useSaveView() {
  const queryClient = useQueryClient();
  const fail = useContext(WriteFailures)!;
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
    onError: fail,
  });
}

/**
 * The quick filters' writes (F162.6), for everyone: one made under a name, of a chip as a state
 * writes it, its amount the cost; one removed. Neither is renamed nor edited. Each reads the counts
 * again, which list every quick filter. A view that had a removed one on shows without it, so the
 * normal forms the page holds are asked again, the server's now dropping it.
 */
export function useQuickFilterWrites() {
  const queryClient = useQueryClient();
  const fail = useContext(WriteFailures)!;
  const { showSuccess } = useToast();
  const stored = catalogueQuery('stored').queryKey;
  const quickFilters = (change: (held: QuickFilter[]) => QuickFilter[]) =>
    queryClient.setQueryData<Catalogue>(stored, (was) => (was?.quick_filters == null ? was : { ...was, quick_filters: change(was.quick_filters) }));

  const add = useMutation({
    mutationFn: async ({ label, chip }: { label: string; chip: string }) => {
      const { data, error, response } = await api.POST('/api/dashboard/quick-filters', { body: { label, chip, amount: 'cost' }, headers });
      if (error !== undefined) throw toApiError(error, response.status);
      return data;
    },
    onSuccess: (made) => {
      quickFilters((held) => [...held, made]);
      void quickFiltersChanged(queryClient);
      showSuccess(`Added the quick filter "${made.label}" for everyone`);
    },
    onError: fail,
  });

  const remove = useMutation({
    mutationFn: async (quickFilter: QuickFilter) => {
      const { error, response } = await api.DELETE('/api/dashboard/quick-filters/{quick_filter_id}', { params: { path: { quick_filter_id: quickFilter.id } }, headers });
      if (error !== undefined) throw toApiError(error, response.status);
    },
    onSuccess: (_, quickFilter) => {
      quickFilters((held) => held.filter((each) => each.id !== quickFilter.id));
      void quickFiltersChanged(queryClient);
      void normalFormsChanged(queryClient);
      showSuccess(`Removed the quick filter "${quickFilter.label}" for everyone`);
    },
    onError: (error) => {
      fail(error);
      void queryClient.invalidateQueries({ queryKey: stored });
    },
  });

  return { add, remove };
}

/**
 * `written`, a tab's state, without the ratio `key`. A state the page does not read, a link's text
 * the server normalises, is left as it is: the server drops a ratio by a key that is gone as it
 * reads it.
 */
function withoutRatioIn(written: string, key: string): string {
  try {
    const state = readState(written);
    return namesRatio(state, key) ? writeState(withoutRatio(state, key)) : written;
  } catch (error) {
    if (error instanceof StateFormError) return written;
    throw error;
  }
}

/**
 * The custom ratios' writes (F163.6), for everyone: one made or changed, its name, its two sides and
 * the format the person picked; one of a person's removed. Each reads again the catalogue's
 * measures, whose ratios it changes, and what is stored; a change reads again the figures of every
 * state that names the ratio, which show it changed. A remove takes the ratio out of every open tab,
 * now and as it opened, and asks again every normal form the page holds, the server's now dropping it.
 * A name another person's ratio has is the form's to say, and no banner's.
 */
export function useRatioWrites() {
  const queryClient = useQueryClient();
  const fail = useContext(WriteFailures)!;
  const { showSuccess } = useToast();
  const moves = useViewTabMoves();
  const stored = () =>
    Promise.all([queryClient.invalidateQueries({ queryKey: catalogueQuery('measures').queryKey }), queryClient.invalidateQueries({ queryKey: catalogueQuery('stored').queryKey })]);

  const save = useMutation({
    mutationFn: async ({ ratio, body }: { ratio: CustomRatio | null; body: RatioWrite }) => {
      const { data, error, response } =
        ratio === null
          ? await api.POST('/api/dashboard/custom-ratios', { body, headers })
          : await api.PUT('/api/dashboard/custom-ratios/{ratio_id}', { params: { path: { ratio_id: ratio.id } }, body, headers });
      if (error !== undefined) throw toApiError(error, response.status);
      return data;
    },
    // The catalogue's measures read again before the form closes, so that the ratio is named as it is drawn.
    onSuccess: async (saved, { ratio }) => {
      await stored();
      if (ratio !== null) void ratioChanged(queryClient, saved.key);
      showSuccess(ratio === null ? `Added the ratio "${saved.name}" for everyone` : `Changed the ratio "${saved.name}" for everyone`);
    },
    onError: (error) => {
      if (!isNameTaken(error)) fail(error);
    },
  });

  const remove = useMutation({
    mutationFn: async (ratio: CustomRatio) => {
      const { error, response } = await api.DELETE('/api/dashboard/custom-ratios/{ratio_id}', { params: { path: { ratio_id: ratio.id } }, headers });
      if (error !== undefined) throw toApiError(error, response.status);
    },
    onSuccess: (_, ratio) => {
      moves.rewritten((written) => withoutRatioIn(written, ratio.key));
      void stored();
      void normalFormsChanged(queryClient);
      showSuccess(`Removed the ratio "${ratio.name}" for everyone`);
    },
    onError: (error) => {
      fail(error);
      void stored();
    },
  });

  return { save, remove };
}

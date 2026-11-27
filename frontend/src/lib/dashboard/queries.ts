/**
 * The dashboard's reads (F160.6). A view's figures are queries keyed by its state without its
 * look-only parts (`withoutLook` in `state.ts`), so that a change of look asks nothing, each under
 * `FIGURES`, the first part of the key of every query the walk's event makes stale
 * (`use-walk-reads.ts`); each read takes the query's signal, so that one superseded is cancelled.
 * They are kept until the walk's event, never stale by age.
 *
 * The quick filters' counts and amounts are a task's answer over the stream (`task.ts`), read as a
 * figure is: a walk asks them again with the view's rows. By's counts are a task's too, which By's
 * panel follows as it opens (`use-by-counts.ts`), kept under `FIGURES` by no query's read: a walk
 * leaves them stale and asks nothing.
 *
 * A state from outside the page, a link opened cold, is read through the server's normal form
 * first (`GET /api/dashboard/address`), since the page reads the server's forms alone: the
 * address of a text is the server's at the page's first read of it, and a normal form is its own.
 *
 * What a view may name, the catalogue's parts, and the person's favourites are no figures: the
 * walk's event leaves them. A write of the dashboard's reads again what it changed, and no more.
 *
 * No route labels a value of a dimension, so a value the page was not told the label of, by a row
 * it drilled from or a pane's values, is looked up among the values of a scope that holds it
 * (`labelQuery`, `valuesNamed` in `scope.ts`): a value has one label in every scope, so the lookup
 * is keyed without the scope it was asked in, and the walk's event leaves it.
 */

import { queryOptions, type QueryClient } from '@tanstack/react-query';
import { toApiError } from '@/lib/api/api-error';
import { api } from '@/lib/api/client';
import type { components } from '@/lib/api/generated/types';
import type { Rows } from './rows-layout';
import { lookOf, readState } from './state';
import { taskAnswer, type Listen } from './task';

type Address = components['schemas']['AddressResponseSchema.b67cf98'];
type Values = components['schemas']['ValuesResponseSchema.b67cf98'];
export type Catalogue = components['schemas']['CatalogueResponseSchema.b67cf98'];
export type Favourites = components['schemas']['FavouritesSchema.ddf95d6'];
export type SavedView = components['schemas']['CatalogueResponseSchema.b67cf98.SavedViewSchema'];
export type QuickFilter = components['schemas']['CatalogueResponseSchema.b67cf98.QuickFilterSchema'];
type CataloguePart = Catalogue['part'];

/** The first part of the key of every query of the record's figures. */
export const FIGURES = 'dashboard';

/** The `meta` flag of a query whose answer comes over the stream: one the stream dropped never lands. */
export const OVER_STREAM = 'overStream';

/** The quick filters' counts and amounts of a view (`backend/app/schemas/dashboard.py`, `QuickFilterCountsSchema`), the task's result. */
interface QuickFilterCounts {
  quick_filters: { key: string; count: number; amount: number | null }[];
}

const ADDRESS = 'dashboard.address';

const COUNTS = 'quick-filters';

const BY_COUNTS = 'by-counts';

const CATALOGUE = 'dashboard.catalogue';

const FAVOURITES = 'dashboard.favourites';

const LABEL = 'dashboard.label';

const PREFIX = '#dash/';

/** An address's state, its `#dash/` read off. */
export const stateOf = (address: string): string => (address.startsWith(PREFIX) ? address.slice(PREFIX.length) : address);

/** The normal form of `written`, a state as an address carries it; a normal form is its own, once read. */
export function addressQuery(queryClient: QueryClient, written: string) {
  return queryOptions({
    queryKey: [ADDRESS, written],
    queryFn: async ({ signal }): Promise<Address> => {
      const { data, error, response } = await api.GET('/api/dashboard/address', { params: { query: { state: written } }, signal });
      if (error !== undefined) throw toApiError(error, response.status);
      const normal = stateOf(data.address);
      if (normal !== written) queryClient.setQueryData([ADDRESS, normal], data);
      return data;
    },
    staleTime: Infinity,
  });
}

/** `address`, a normal form the server wrote, known as its own, so that the page asks nothing of it. */
export function knowNormal(queryClient: QueryClient, address: string): void {
  const normal = stateOf(address);
  queryClient.setQueryData<Address>([ADDRESS, normal], { address, look: lookOf(readState(normal)), notes: [] });
}

/** Every normal form the page holds asked again where it is read, the server's forms having changed under them. */
export function normalFormsChanged(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: [ADDRESS] });
}

/** A view's rows, `key` its state in its normal form without its look-only parts. */
export function rowsQuery(key: string) {
  return queryOptions({
    queryKey: [FIGURES, 'rows', key],
    queryFn: async ({ signal }): Promise<Rows> => {
      const { data, error, response } = await api.GET('/api/dashboard/rows', { params: { query: { state: key } }, signal });
      if (error !== undefined) throw toApiError(error, response.status);
      return data;
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

/** The values of `dimension` in `scope`, a state without its look-only parts, less its own chips: those whose label or key holds `search`. */
export function valuesQuery(scope: string, dimension: string, search: string) {
  return queryOptions({
    queryKey: [FIGURES, 'values', scope, dimension, search],
    queryFn: async ({ signal }): Promise<Values> => {
      const query = { state: scope, dimension, ...(search === '' ? {} : { search }) };
      const { data, error, response } = await api.GET('/api/dashboard/values', { params: { query }, signal });
      if (error !== undefined) throw toApiError(error, response.status);
      return data;
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

/**
 * The quick filters' counts and amounts in a view's scope, `key` its state in its normal form without
 * its look-only parts, under the quick filters that are on: each one's count of what it keeps and its
 * figure's sum over it.
 */
export function quickFilterCountsQuery(key: string, listen: Listen) {
  return queryOptions({
    queryKey: [FIGURES, COUNTS, key],
    queryFn: ({ signal }) =>
      taskAnswer<QuickFilterCounts>(listen, signal, async () => {
        const { data, error, response } = await api.POST('/api/dashboard/counts/quick-filters', { params: { query: { state: key } }, signal });
        if (error !== undefined) throw toApiError(error, response.status);
        return data.task_id;
      }),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    // A read asked again starts its task again, which holds the engine again: a failure waits for its Retry.
    retry: false,
    meta: { [OVER_STREAM]: true },
  });
}

/** The quick filters' counts asked again in every scope, a quick filter made or removed. */
export function quickFiltersChanged(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: [FIGURES, COUNTS] });
}

/** Where By's counts in `scope` are kept, which `use-by-counts.ts` writes and no read fetches. */
export const byCountsKey = (scope: string) => [FIGURES, BY_COUNTS, scope] as const;

/** A value's text as a state writes it, decoded; none for the value with none. */
export const valueText = (key: Values['values'][number]['key']): string | null => (key === null ? null : String(key));

/**
 * The label of `dimension`'s value `value`, looked up among its values in `scope`, a state; none
 * where the scope holds no such value, or the value is its own label. A label found is kept; a
 * value not found is looked up again where a view next shows it.
 */
export function labelQuery(dimension: string, value: string, scope: string) {
  return queryOptions({
    queryKey: [LABEL, dimension, value],
    queryFn: async ({ signal }): Promise<string | null> => {
      const query = { state: scope, dimension, search: value };
      const { data, error, response } = await api.GET('/api/dashboard/values', { params: { query }, signal });
      if (error !== undefined) throw toApiError(error, response.status);
      const found = data.values.find((each) => valueText(each.key) === value);
      return found === undefined ? null : (found.label ?? value);
    },
    staleTime: (query) => (query.state.data === null ? 0 : Infinity),
    refetchOnWindowFocus: false,
  });
}

/** The label of `dimension`'s value `value`, which the page was told, none where the value is its own, known so that it is never looked up. */
export function knowLabel(queryClient: QueryClient, dimension: string, value: string, label: string | null): void {
  queryClient.setQueryData(labelQuery(dimension, value, '').queryKey, label ?? value);
}

/** A part of the catalogue: `stored`, what the dashboard stores, is everyone's and changes under the page. */
export function catalogueQuery(part: CataloguePart) {
  return queryOptions({
    queryKey: [CATALOGUE, part],
    queryFn: async ({ signal }): Promise<Catalogue> => {
      const { data, error, response } = await api.GET('/api/dashboard/catalogue', { params: { query: { part } }, signal });
      if (error !== undefined) throw toApiError(error, response.status);
      return data;
    },
    staleTime: Infinity,
  });
}

/** The signed-in person's favourites: the views they starred, in the order starred, and their dimensions. */
export function favouritesQuery() {
  return queryOptions({
    queryKey: [FAVOURITES],
    queryFn: async ({ signal }): Promise<Favourites> => {
      const { data, error, response } = await api.GET('/api/dashboard/favourites', { signal });
      if (error !== undefined) throw toApiError(error, response.status);
      return data;
    },
    staleTime: Infinity,
  });
}

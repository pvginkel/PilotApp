/**
 * The dashboard's reads (F160.6). A view's figures are queries keyed by its state without its
 * look-only parts (`withoutLook` in `state.ts`), so that a change of look asks nothing, each under
 * `FIGURES`, the first part of the key of every query the walk's event makes stale
 * (`use-walk-reads.ts`); each read takes the query's signal, so that one superseded is cancelled.
 * They are kept until the walk's event, never stale by age.
 *
 * A state from outside the page, a link opened cold, is read through the server's normal form
 * first (`GET /api/dashboard/address`), since the page reads the server's forms alone: the
 * address of a text is the server's at the page's first read of it, and a normal form is its own.
 *
 * What a view may name, the catalogue's parts, and the person's favourites are no figures: the
 * walk's event leaves them. A write of the dashboard's reads again what it changed, and no more.
 */

import { queryOptions, type QueryClient } from '@tanstack/react-query';
import { toApiError } from '@/lib/api/api-error';
import { api } from '@/lib/api/client';
import type { components } from '@/lib/api/generated/types';
import type { Rows } from './rows-layout';

type Address = components['schemas']['AddressResponseSchema.b67cf98'];
export type Catalogue = components['schemas']['CatalogueResponseSchema.b67cf98'];
export type Favourites = components['schemas']['FavouritesSchema.ddf95d6'];
export type SavedView = components['schemas']['CatalogueResponseSchema.b67cf98.SavedViewSchema'];
type CataloguePart = Catalogue['part'];

/** The first part of the key of every query of the record's figures. */
export const FIGURES = 'dashboard';

const ADDRESS = 'dashboard.address';

const CATALOGUE = 'dashboard.catalogue';

const FAVOURITES = 'dashboard.favourites';

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

/** The catalogue's parts a view is worded from (`describe.ts`), each read once in the page. */

import { useQuery } from '@tanstack/react-query';
import type { Words } from '@/lib/dashboard/describe';
import { catalogueQuery } from '@/lib/dashboard/queries';

export function useViewWords(): Words {
  return {
    dimensions: useQuery(catalogueQuery('dimensions')).data,
    measures: useQuery(catalogueQuery('measures')).data,
    time: useQuery(catalogueQuery('time')).data,
  };
}

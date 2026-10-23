/**
 * An item's document, as GET /api/items/<id>/document reads it on its own (F28): its timeline
 * entry and its project, with its text as Done fixed it where Done did (F13.3). It refetches when
 * the window comes back into focus, after the person's own writes, which invalidate every query,
 * and on its project's live event (F80.2; use-project-events.ts).
 */

import { useGetItemsDocumentByItemId } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

export type ItemDocument = components['schemas']['ItemDocumentSchema.1fdd8ae'];

export function useItemDocument(id: string) {
  const query = useGetItemsDocumentByItemId({ path: { item_id: id } }, { refetchOnWindowFocus: 'always' });
  useUiStateInstrumentation('overlay.document', { isLoading: query.isLoading, error: query.error });
  return query;
}

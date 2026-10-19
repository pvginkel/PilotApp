/**
 * The signed-in person, as GET /api/people/self answers: on the record once their handle is
 * chosen, the token's name until then. Reading it records the sign-in.
 */

import { useGetPeopleSelf } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

export type Self = components['schemas']['SelfResponseSchema.d1d9f70'];

export function useSelf() {
  const query = useGetPeopleSelf();
  useUiStateInstrumentation('people.self', { isLoading: query.isLoading, error: query.error });
  return query;
}

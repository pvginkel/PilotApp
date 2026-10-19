/**
 * The signed-in person, as GET /api/people/self answers: on the record once their handle is
 * chosen, the token's name until then. Reading it records the sign-in.
 */

import { createContext, useContext } from 'react';
import { useGetPeopleSelf } from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

export type Self = components['schemas']['SelfResponseSchema.d1d9f70'];

/** The signed-in person once their handle is chosen: on the record, with their avatar slot. */
type Person = Self & { handle: string; name: string; avatar_slot: number };

/** The API answers a person with a handle with their name on the record and their slot. */
export function isPerson(self: Self): self is Person {
  return self.handle !== null;
}

export function useSelf() {
  const query = useGetPeopleSelf();
  useUiStateInstrumentation('people.self', { isLoading: query.isLoading, error: query.error });
  return query;
}

const PersonContext = createContext<Person | null>(null);

/** The shell provides the person to every screen under it, and opens none before the handle. */
export const PersonProvider = PersonContext.Provider;

export function usePerson(): Person {
  const person = useContext(PersonContext);
  if (person === null) throw new Error('usePerson() is read only under the shell, once the handle is chosen');
  return person;
}

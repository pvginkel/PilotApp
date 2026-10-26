/** Who a person's message in the chat is from, as its avatar and its name draw them. */

import type { components } from '@/lib/api/generated/types';

type Member = components['schemas']['ProjectHeadSchema.e86ccd6.MemberSchema'];

export interface Someone {
  name: string;
  /** Null where nothing is known to take them from: a user icon stands in. */
  initials: string | null;
  slot: number | null;
}

export interface ChatPeople {
  /** The signed-in person's handle. */
  me: string;
  /** A person by their handle: the signed-in person and the project's members as the record has them, anyone else by the handle alone. */
  who: (handle: string) => Someone;
}

/** A person as the record has them: a member, or the signed-in person, whose initials can be none. */
type Person = Omit<Member, 'initials'> & { initials: string | null };

export function chatPeople(me: Person, members: readonly Person[]): ChatPeople {
  const byHandle = new Map<string, Someone>(
    [...members, me].map((person) => [person.handle, { name: person.name, initials: person.initials, slot: person.avatar_slot }]),
  );
  return { me: me.handle, who: (handle) => byHandle.get(handle) ?? { name: handle, initials: null, slot: null } };
}

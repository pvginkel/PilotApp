/** A person or Pilot on the timeline, as the API names them, in their avatar (F106, F132). */

import { Avatar } from '@/components/shared/avatar';
import type { TimelineUser } from '@/hooks/use-timeline';

export function UserAvatar({ user, size }: { user: TimelineUser; size?: 'sm' | 'xs' }) {
  const who = user.kind === 'agent' ? 'pilot' : { name: user.name, initials: user.initials, slot: user.avatar_slot };
  return <Avatar who={who} size={size} />;
}

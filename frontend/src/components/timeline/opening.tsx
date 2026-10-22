/**
 * The opening (F18.1, F18.2): the words that started the project, verbatim, as a bubble beside its
 * author's avatar, "<who> started this project · <time>" over them, folding with Show more. It has
 * no head and never collapses. Arrived, or gone to at its address, its bubble flashes.
 */

import type { AnimationEvent } from 'react';
import { Fold } from '@/components/shared/fold';
import { LinkedText } from '@/components/shared/linked-text';
import { Time } from '@/components/shared/time';
import { UserAvatar } from '@/components/timeline/user-avatar';
import type { TimelineItem } from '@/hooks/use-timeline';
import { usePerson } from '@/hooks/use-self';
import { cn } from '@/lib/utils';

interface OpeningProps {
  item: TimelineItem;
  fresh: boolean;
  onFlashed: () => void;
}

export function Opening({ item, fresh, onFlashed }: OpeningProps) {
  const me = usePerson();
  // The API names the opening's author and gives its words.
  const author = item.author!;
  const flashed = (event: AnimationEvent) => event.target === event.currentTarget && onFlashed();
  return (
    <div className={cn('prompt', fresh && 'fresh')} data-testid="timeline.opening" data-item-id={item.id}>
      <UserAvatar user={author} size="sm" />
      <div className="bubble" onAnimationEnd={flashed}>
        <div className="who" data-testid="timeline.opening.who">
          <b>{author.handle === me.handle ? 'You' : author.name}</b> started this project ·{' '}
          <Time at={item.created_at} format="clock" testId="timeline.opening.time" />
        </div>
        <Fold testId="timeline.opening.words">
          <div className="said">
            <LinkedText text={item.words!} />
          </div>
        </Fold>
      </div>
    </div>
  );
}

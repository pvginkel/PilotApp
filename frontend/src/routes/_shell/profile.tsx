/**
 * The profile page (F134, opened from the profile menu, F126): who the person is and their
 * handle, shown and not editable (F137); their notification token and, beside it, the alarms
 * switch (F142.1).
 */

import { createFileRoute } from '@tanstack/react-router';
import { AlarmsSwitch, NotificationToken } from '@/components/people/profile-notifications';
import { Avatar } from '@/components/shared/avatar';
import { usePerson } from '@/hooks/use-self';

export const Route = createFileRoute('/_shell/profile')({
  component: Profile,
});

function Profile() {
  const person = usePerson();
  return (
    <div className="people-page" data-testid="profile">
      <section>
        <h1>Profile</h1>
        <div className="profile-who">
          <Avatar who={{ name: person.name, initials: person.initials, slot: person.avatar_slot }} />
          <span data-testid="profile.name">{person.name}</span>
        </div>
        <dl className="profile-fields">
          <dt>Handle</dt>
          <dd>
            <span className="handle" data-testid="profile.handle">
              {person.handle}
            </span>
            <p>The short name that stands for you in Pilot&rsquo;s files. It cannot be changed.</p>
          </dd>
          <dt>Notification token</dt>
          <dd>
            <NotificationToken set={person.notification_token_set} />
          </dd>
          <dt>Alarms</dt>
          <dd>
            <AlarmsSwitch on={person.alarms} tokenSet={person.notification_token_set} />
          </dd>
        </dl>
      </section>
    </div>
  );
}

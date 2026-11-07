/**
 * The gold bar's offer of this browser's notifications (F146.2): across the full width of the
 * top, over the top bar off a phone and over the conditions' bar on one, at a browser's first open
 * while its notifications are off and its permission not refused. Turn on asks the permission
 * from its tap; Turn on, Not now, or the profile page's switch turning them on, and it never shows
 * in that browser again.
 */

import { BellRing } from 'lucide-react';
import { useDeviceNotifications } from '@/hooks/use-device-notifications';
import { rememberInBrowser, useBrowserState } from '@/lib/browser-state';

const FORM = 'shell.notifications-offer';

export function NotificationsOffer({ handle }: { handle: string }) {
  const { unavailable, on, blocked, turnOn } = useDeviceNotifications(handle);
  const { notificationsOffered } = useBrowserState();
  if (unavailable !== null || on !== false || blocked || notificationsOffered) return null;
  return (
    <div className="notifications-offer" role="region" aria-label="Notifications" data-testid="shell.notifications-offer">
      <div className="gold-line">
        <BellRing className="icon" aria-hidden="true" />
        <div className="gold-body">
          <p>
            <strong>Turn on notifications on this device?</strong> Pilot tells you here what waits on you in your
            projects, while you are not in Pilot.
          </p>
          <div className="gold-actions">
            <button
              type="button"
              className="gold-btn"
              onClick={() => {
                rememberInBrowser({ notificationsOffered: true });
                turnOn(FORM);
              }}
              data-testid="shell.notifications-offer.on"
            >
              Turn on
            </button>
            <button
              type="button"
              className="gold-btn"
              onClick={() => rememberInBrowser({ notificationsOffered: true })}
              data-testid="shell.notifications-offer.not-now"
            >
              Not now
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

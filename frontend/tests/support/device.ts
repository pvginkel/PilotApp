/**
 * A spec's page as its device (F94, F142, F147): a push handed to its service worker as a push
 * service hands it (CDP `ServiceWorker.deliverPushMessage`), the notifications standing there
 * (`getNotifications()`), and its visibility, which a headless page never changes by itself:
 * `hide()` and `foreground()` set what the page reads of it and tell it, as a browser does. A push
 * shows only in Chromium's full build with the notifications permission granted
 * (`test.use({ channel: 'chromium', permissions: ['notifications'] })`): the suite's headless shell
 * keeps the permission denied and shows none.
 */

import { expect, type CDPSession, type Page } from '@playwright/test';
import type { UiStateTestEvent } from '@/lib/test/test-events';
import { getTestEventBuffer } from './helpers/test-events';

/** A push as the server sends it (`backend/app/services/web_push.py`, `Push`). */
export interface Push {
  title: string;
  body: string;
  tag: string;
  url: string;
  renotify: boolean;
}

/** A notification standing on the device. */
interface Shown {
  title: string;
  body: string;
  tag: string;
  renotify: boolean;
  silent: boolean | null;
  icon: string;
  url: string;
}

export class Device {
  private cdp: Promise<{ session: CDPSession; registrationId: string }> | null = null;

  constructor(private readonly page: Page) {}

  /**
   * Hands `push` to the page's service worker, resolving once it stands on the device. Headless
   * Chromium drops a notification `getNotifications()` reads while it is being displayed, so it
   * goes once the page reads none to close them (`closed()`), and nothing reads before DevTools
   * tells it displayed, under its tag.
   */
  async deliver(push: Push): Promise<void> {
    const { session, registrationId } = await (this.cdp ??= this.attach());
    const displayed = new Promise<void>((resolve) => {
      const listener = ({ backgroundServiceEvent }: { backgroundServiceEvent: { eventName: string; instanceId: string } }) => {
        if (backgroundServiceEvent.eventName === 'Notification displayed' && backgroundServiceEvent.instanceId === push.tag) {
          session.off('BackgroundService.backgroundServiceEventReceived', listener);
          resolve();
        }
      };
      session.on('BackgroundService.backgroundServiceEventReceived', listener);
    });
    await this.closed();
    await session.send('ServiceWorker.deliverPushMessage', {
      origin: new URL(this.page.url()).origin,
      registrationId,
      data: JSON.stringify(push),
    });
    await displayed;
    const shown = async () =>
      (await this.notifications()).some((each) => each.tag === push.tag && each.body === push.body && each.renotify === push.renotify);
    await expect.poll(shown, { message: `the push under ${push.tag} shows` }).toBe(true);
  }

  /**
   * Resolves once the page, as loaded, reads none of its notifications to close them: the last of
   * its `shell.closing` states is ready (`use-app-page.ts`), each visible load closing the alarms'
   * as it starts.
   */
  private async closed(): Promise<void> {
    const load = await this.page.evaluate(() => performance.timeOrigin);
    const buffer = getTestEventBuffer(this.page);
    const state = () =>
      buffer
        .snapshot(0)
        .events.filter((event): event is UiStateTestEvent => event.kind === 'ui_state' && event.scope === 'shell.closing' && event.metadata?.load === load)
        .at(-1)?.phase;
    await expect.poll(state, { message: 'the page reads none of its notifications to close them' }).toBe('ready');
  }

  /** The notifications standing on the device, in the order they first showed. */
  async notifications(): Promise<Shown[]> {
    return this.page.evaluate(async () => {
      const registration = await navigator.serviceWorker.ready;
      return (await registration.getNotifications()).map((notification) => ({
        title: notification.title,
        body: notification.body,
        tag: notification.tag,
        renotify: (notification as Notification & { renotify: boolean }).renotify,
        silent: notification.silent,
        icon: notification.icon,
        url: (notification.data as { url: string }).url,
      }));
    });
  }

  /** The tags of the notifications standing on the device. */
  async tags(): Promise<string[]> {
    return (await this.notifications()).map((notification) => notification.tag).sort();
  }

  /** The page goes to the background: hidden, as a tab left or a phone's app put away. */
  async hide(): Promise<void> {
    await this.visibility('hidden');
  }

  /** The page comes back to the foreground. */
  async foreground(): Promise<void> {
    await this.visibility('visible');
  }

  private async visibility(state: DocumentVisibilityState): Promise<void> {
    await this.page.evaluate((state) => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => state === 'hidden' });
      document.dispatchEvent(new Event('visibilitychange'));
    }, state);
  }

  /** The page's service worker as CDP names it, once it is active. */
  private async attach(): Promise<{ session: CDPSession; registrationId: string }> {
    const scope = await this.page.evaluate(async () => (await navigator.serviceWorker.ready).scope);
    const session = await this.page.context().newCDPSession(this.page);
    const registrationId = new Promise<string>((resolve) => {
      session.on('ServiceWorker.workerRegistrationUpdated', ({ registrations }) => {
        const registration = registrations.find((each) => each.scopeURL === scope && !each.isDeleted);
        if (registration !== undefined) resolve(registration.registrationId);
      });
    });
    await session.send('ServiceWorker.enable');
    await session.send('BackgroundService.setRecording', { shouldRecord: true, service: 'notifications' });
    await session.send('BackgroundService.startObserving', { service: 'notifications' });
    return { session, registrationId: await registrationId };
  }
}

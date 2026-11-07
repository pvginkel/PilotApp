/**
 * This browser's notifications (F146): its push subscription, written for the signed-in person by
 * the profile page's switch or the gold bar's offer and deleted by the switch's off and by
 * sign-out, and the browser's permission, which is the browser's own: the switch's off leaves it
 * granted, so on again asks nothing. The browser's storage keeps whose the subscription is (F133),
 * so that a person signing in where another's session ended without a sign-out reads theirs off.
 */

import { useEffect, useSyncExternalStore } from 'react';
import { useAuthContext } from '@/contexts/auth-context';
import { useToast } from '@/hooks/use-toast';
import {
  useDeletePeopleSelfPushSubscriptions,
  useGetWebPush,
  usePostPeopleSelfPushSubscriptions,
} from '@/lib/api/generated/hooks';
import type { components } from '@/lib/api/generated/types';
import { rememberInBrowser, useBrowserState } from '@/lib/browser-state';
import { trackFormError, trackFormSubmit, trackFormSuccess } from '@/lib/test/form-instrumentation';
import { useUiStateInstrumentation } from '@/lib/test/ui-state';

type SubscriptionBody = components['schemas']['PushSubscriptionSchema.efd40b8'];

/** Push in this browser: absent outside a secure context, as on the dev server reached by its address. */
const SUPPORTED = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

const SWITCH_FORM = 'people.device-notifications';
const SIGN_OUT_FORM = 'shell.sign-out';

interface Device {
  permission: NotificationPermission;
  /** The browser's subscription with its push service; undefined until read. */
  subscription: PushSubscription | null | undefined;
  /** A turn on or off under way, from the switch or the offer. */
  busy: boolean;
}

let device: Device = { permission: SUPPORTED ? Notification.permission : 'default', subscription: undefined, busy: false };
const listeners = new Set<() => void>();
let read: Promise<void> | null = null;

function change(next: Partial<Device>): void {
  device = { ...device, ...next };
  listeners.forEach((listener) => listener());
}

function listen(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Reads the browser's subscription, once, when the first screen that shows it mounts. */
function readSubscription(): void {
  read ??= navigator.serviceWorker.ready
    .then((registration) => registration.pushManager.getSubscription())
    .then((subscription) => change({ subscription }));
}

/**
 * Asks the permission where the person has not answered it, from the tap that calls this, then
 * subscribes the browser with the stage's key; null while the permission is not granted.
 */
async function subscribeBrowser(publicKey: string): Promise<PushSubscription | null> {
  const permission = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
  change({ permission });
  if (permission !== 'granted') return null;
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: publicKey });
}

function body(subscription: PushSubscription): SubscriptionBody {
  // A subscription made with an application server key always carries both keys.
  const keys = subscription.toJSON().keys as SubscriptionBody['keys'];
  return { endpoint: subscription.endpoint, keys: { p256dh: keys.p256dh, auth: keys.auth } };
}

/** Why this browser cannot turn its notifications on: the deployment sends none, or the browser has no push. */
type Unavailable = 'no-key' | 'unsupported';

interface DeviceNotifications {
  unavailable: Unavailable | null;
  /** Whether this browser's subscription is the person's; null while the stage's key or the subscription is read. */
  on: boolean | null;
  /** The browser's permission refused: only its site settings undo it. */
  blocked: boolean;
  busy: boolean;
  /** Turns them on, its test events under `form`. */
  turnOn: (form?: string) => void;
  turnOff: () => void;
}

/** This browser's notifications for the person who holds `handle`. */
export function useDeviceNotifications(handle: string): DeviceNotifications {
  const setup = useGetWebPush();
  const { permission, subscription, busy } = useSyncExternalStore(listen, () => device);
  const { subscribedFor } = useBrowserState();
  const post = usePostPeopleSelfPushSubscriptions();
  const remove = useDeletePeopleSelfPushSubscriptions();
  const { showException } = useToast();
  useEffect(() => {
    if (SUPPORTED) readSubscription();
  }, []);

  const publicKey = setup.data?.public_key;
  const unavailable: Unavailable | null = !SUPPORTED ? 'unsupported' : publicKey === null ? 'no-key' : null;
  const on =
    unavailable !== null ? false : publicKey === undefined || subscription === undefined ? null : subscription !== null && subscribedFor === handle;
  useUiStateInstrumentation('notifications.device', {
    isLoading: on === null,
    error: setup.error,
    getReadyMetadata: () => ({ on, unavailable, permission }),
  });

  const turnOn = (form = SWITCH_FORM) => {
    if (typeof publicKey !== 'string' || busy) return;
    trackFormSubmit(form, { on: true });
    change({ busy: true });
    // Kept in the store, not the component: the request outlives the offer that sent it.
    void (async () => {
      let made: PushSubscription | null;
      try {
        made = await subscribeBrowser(publicKey);
      } catch (error) {
        change({ busy: false });
        showException('Cannot turn notifications on in this browser', error);
        trackFormError(form, { on: true });
        return;
      }
      if (made === null) {
        change({ busy: false });
        trackFormError(form, { on: true, permission: device.permission });
        return;
      }
      try {
        await post.mutateAsync({ body: body(made) });
      } catch {
        // The query client toasts the refusal (UI-2).
        change({ busy: false });
        trackFormError(form, { on: true });
        return;
      }
      rememberInBrowser({ subscribedFor: handle, notificationsOffered: true });
      change({ subscription: made, busy: false });
      trackFormSuccess(form, { on: true });
    })();
  };

  const turnOff = () => {
    if (!subscription || busy) return;
    trackFormSubmit(SWITCH_FORM, { on: false });
    change({ busy: true });
    void (async () => {
      try {
        await remove.mutateAsync({ query: { endpoint: subscription.endpoint } });
      } catch {
        // The query client toasts the refusal (UI-2).
        change({ busy: false });
        trackFormError(SWITCH_FORM, { on: false });
        return;
      }
      rememberInBrowser({ subscribedFor: null });
      change({ subscription: null, busy: false });
      await subscription.unsubscribe();
      trackFormSuccess(SWITCH_FORM, { on: false });
    })();
  };

  return { unavailable, on, blocked: permission === 'denied', busy, turnOn, turnOff };
}

/** The browser's subscription, whoever it was written for; none where the browser has no push or no service worker yet. */
async function currentSubscription(): Promise<PushSubscription | null> {
  if (!SUPPORTED) return null;
  const registration = await navigator.serviceWorker.getRegistration();
  return registration === undefined ? null : registration.pushManager.getSubscription();
}

/**
 * Signs the person out, this browser's subscription deleted and unsubscribed first (F146.3), so
 * that a signed-out browser is pushed nothing. A refused delete is the query client's to toast,
 * and the person stays signed in.
 */
export function useSignOut(): () => void {
  const { logout } = useAuthContext();
  const remove = useDeletePeopleSelfPushSubscriptions();
  return () => {
    trackFormSubmit(SIGN_OUT_FORM);
    void (async () => {
      const subscription = await currentSubscription();
      if (subscription !== null) {
        try {
          await remove.mutateAsync({ query: { endpoint: subscription.endpoint } });
        } catch {
          trackFormError(SIGN_OUT_FORM);
          return;
        }
        rememberInBrowser({ subscribedFor: null });
        change({ subscription: null });
        await subscription.unsubscribe();
      }
      trackFormSuccess(SIGN_OUT_FORM);
      logout();
    })();
  };
}

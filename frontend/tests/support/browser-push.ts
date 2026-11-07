/**
 * A spec's browser's push (F146). The suite's headless Chromium subscribes to no real push service
 * ("Registration failed - permission denied") and keeps its notifications permission denied
 * whatever is granted, so `install()`, before the page loads, gives the page a permission and a
 * PushManager of its own: the permission `default` until the page asks it, then the answer the
 * spec gave, and a subscription the backend's fake push service issues
 * (/api/testing/push-service/fake/subscribe), its endpoint the fake's. Both are kept in the page's
 * storage, as a browser keeps them across loads. Without `install()` the page has the shell's own:
 * its permission denied.
 */

import { expect, type Page } from '@playwright/test';

type Permission = 'default' | 'granted' | 'denied';

interface Install {
  /** The permission before the page asks it. */
  permission?: Permission;
  /** What the browser's prompt answers. */
  answer?: Exclude<Permission, 'default'>;
}

/** A subscription as `PushSubscription.toJSON()` gives it. */
interface SubscriptionJson {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

/** A push the browser's push service took, as the fake keeps it: its payload and its headers. */
interface TakenPush {
  title: string;
  body: string;
  tag: string;
  url: string;
  renotify: boolean;
  urgency: string;
  ttl: number;
}

const SUBSCRIBE = '__playwrightPushSubscribe';
const PERMISSION = 'playwright.push.permission';
const PROMPTS = 'playwright.push.prompts';
const SUBSCRIPTION = 'playwright.push.subscription';

export class BrowserPush {
  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
  ) {}

  async install({ permission = 'default', answer = 'granted' }: Install = {}): Promise<void> {
    await this.page.exposeFunction(SUBSCRIBE, async (applicationServerKey: string) => {
      const response = await this.page.request.post(`${this.backendUrl}/api/testing/push-service/fake/subscribe`, {
        data: { application_server_key: applicationServerKey },
      });
      expect(response.status(), await response.text()).toBe(200);
      return (await response.json()) as SubscriptionJson;
    });
    await this.page.addInitScript(
      ({ keys, initial, answered }) => {
        // A frame with no origin of its own (the first about:blank) has no storage.
        if (window.origin === 'null') return;
        if (localStorage.getItem(keys.permission) === null) localStorage.setItem(keys.permission, initial);
        const permission = () => localStorage.getItem(keys.permission) as Permission;
        Object.defineProperty(Notification, 'permission', { configurable: true, get: permission });
        Notification.requestPermission = () => {
          if (permission() === 'default') {
            localStorage.setItem(keys.prompts, String(Number(localStorage.getItem(keys.prompts) ?? '0') + 1));
            localStorage.setItem(keys.permission, answered);
          }
          return Promise.resolve(permission());
        };

        const stored = () => JSON.parse(localStorage.getItem(keys.subscription) ?? 'null') as SubscriptionJson | null;
        const subscription = (json: SubscriptionJson) =>
          ({
            endpoint: json.endpoint,
            expirationTime: null,
            toJSON: () => json,
            unsubscribe: () => {
              localStorage.removeItem(keys.subscription);
              return Promise.resolve(true);
            },
          }) as unknown as PushSubscription;
        const subscribe = (window as unknown as Record<string, (key: string) => Promise<SubscriptionJson>>)[keys.subscribe];
        PushManager.prototype.getSubscription = () => {
          const json = stored();
          return Promise.resolve(json === null ? null : subscription(json));
        };
        // As a browser's: the subscription it holds, else a new one, and none without the permission.
        PushManager.prototype.subscribe = async (options?: PushSubscriptionOptionsInit) => {
          if (permission() !== 'granted') throw new DOMException('Registration failed - permission denied', 'NotAllowedError');
          const json = stored() ?? (await subscribe(options!.applicationServerKey as string));
          localStorage.setItem(keys.subscription, JSON.stringify(json));
          return subscription(json);
        };
      },
      {
        keys: { subscribe: SUBSCRIBE, permission: PERMISSION, prompts: PROMPTS, subscription: SUBSCRIPTION },
        initial: permission,
        answered: answer,
      },
    );
  }

  /** How often the page asked the permission. */
  async prompts(): Promise<number> {
    return Number((await this.page.evaluate((key) => localStorage.getItem(key), PROMPTS)) ?? '0');
  }

  /** Every push the fake push service took for the browser's subscription, in order. */
  async pushes(): Promise<TakenPush[]> {
    const subscription = await this.subscription();
    expect(subscription, 'the browser holds no subscription').not.toBeNull();
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/push-service/fake/pushes`, {
      data: { endpoint: subscription!.endpoint },
    });
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as TakenPush[];
  }

  /** The subscription the browser holds, or none. */
  async subscription(): Promise<SubscriptionJson | null> {
    const json = await this.page.evaluate((key) => localStorage.getItem(key), SUBSCRIPTION);
    return json === null ? null : (JSON.parse(json) as SubscriptionJson);
  }
}

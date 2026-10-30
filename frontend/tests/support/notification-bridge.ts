/**
 * The notification bridge, for a spec: the fake its backend serves itself under
 * /api/testing/notification-bridge (backend-env-extensions.ts points the backend at it). A spec
 * adds a registration of its own, by a fresh name and token (`register()`), and reads what Pilot
 * sent through it, through the fake's verbs, POST /api/testing/notification-bridge/fake/<verb>,
 * which take no sign-in. Registrations hold across the worker's specs, each spec's its own; a
 * bridge held from answering (`hold()`) is the whole fake's, so the fixture answers again after the
 * spec (`restore()`).
 */

import { expect, type Page } from '@playwright/test';
import { makeUnique } from './helpers';

type Priority = 'min' | 'low' | 'default' | 'high' | 'max';

/** A notification a registration took, and whether its submit alerted; a one-shot's `sequence_id` is null. */
interface FakeNotification {
  sequence_id: string | null;
  priority: Priority;
  title: string | null;
  message: string;
  url: string | null;
  alerted: boolean;
}

/** A registration the spec added: its name in the fake, and its bearer token. */
interface Registration {
  name: string;
  token: string;
}

export class NotificationBridge {
  private held = false;

  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
  ) {}

  /** A fresh registration, whose bearer is a fresh token, showing nothing. */
  async register(): Promise<Registration> {
    const registration = { name: makeUnique('phone'), token: makeUnique('invented-token', 16) };
    await this.verb('add-registration', registration);
    return registration;
  }

  /** What the registration shows, per sequence id. */
  async shown(name: string): Promise<Record<string, FakeNotification>> {
    return (await (await this.verb('shown', { name })).json()) as Record<string, FakeNotification>;
  }

  /** The one-shots the registration took, in order. */
  async oneShots(name: string): Promise<FakeNotification[]> {
    return (await (await this.verb('one-shots', { name })).json()) as FakeNotification[];
  }

  /** Every call to the bridge waits for its answer until `answer()`, as a bridge slow to answer. */
  async hold(): Promise<void> {
    await this.verb('unreachable', { on: true, answer: 'stall' });
    this.held = true;
  }

  /** The bridge answers again, a call it held among them. */
  async answer(): Promise<void> {
    await this.verb('unreachable', { on: false });
    this.held = false;
  }

  /** Answers again if the spec held the bridge. */
  async restore(): Promise<void> {
    if (this.held) await this.answer();
  }

  private async verb(verb: string, body: object) {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/notification-bridge/fake/${verb}`, {
      data: body,
    });
    expect([200, 204], await response.text()).toContain(response.status());
    return response;
  }
}

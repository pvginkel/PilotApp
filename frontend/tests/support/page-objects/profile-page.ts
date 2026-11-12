import type { Locator, Page } from '@playwright/test';
import { waitTestEvent } from '../helpers';
import type { FormTestEvent } from '@/lib/test/test-events';

/**
 * The profile page (F134): the person and their handle, this browser's notifications switch, the alarms switch and the
 * switch *Join projects started on my behalf*.
 */
export class ProfilePage {
  readonly root: Locator;
  readonly heading: Locator;
  readonly avatar: Locator;
  readonly name: Locator;
  readonly handle: Locator;
  readonly device: Locator;
  readonly deviceNote: Locator;
  readonly alarms: Locator;
  readonly alarmsNote: Locator;
  readonly joinCalls: Locator;
  readonly joinCallsNote: Locator;

  constructor(private readonly page: Page) {
    this.root = page.getByTestId('profile');
    this.heading = this.root.getByRole('heading');
    this.avatar = this.root.locator('.avatar');
    this.name = page.getByTestId('profile.name');
    this.handle = page.getByTestId('profile.handle');
    this.device = page.getByTestId('profile.device');
    this.deviceNote = page.getByTestId('profile.device.note');
    this.alarms = page.getByTestId('profile.alarms');
    this.alarmsNote = page.getByTestId('profile.alarms.note');
    this.joinCalls = page.getByTestId('profile.join-calls');
    this.joinCallsNote = page.getByTestId('profile.join-calls.note');
  }

  /** Turns this browser's notifications switch; returns once its turn has ended, as `outcome` expects. */
  async turnDevice(outcome: 'success' | 'error' = 'success'): Promise<FormTestEvent> {
    const ended = this.formEvent('people.device-notifications', outcome);
    await this.device.click();
    return ended;
  }

  /** Turns the alarms switch; returns once the page reads the person again, the switch turned. */
  async turnAlarms(): Promise<void> {
    const ended = this.formEvent('people.alarms', 'success');
    await this.alarms.click();
    await ended;
  }

  /** Turns the switch *Join projects started on my behalf*; returns once the page reads the person again, the switch turned. */
  async turnJoinCalls(): Promise<void> {
    const ended = this.formEvent('people.join-calls', 'success');
    await this.joinCalls.click();
    await ended;
  }

  private formEvent(formId: string, phase: 'success' | 'error'): Promise<FormTestEvent> {
    return waitTestEvent<FormTestEvent>(this.page, 'form', (event) => event.formId === formId && event.phase === phase);
  }
}

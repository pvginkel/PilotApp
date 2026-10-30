import type { Locator, Page } from '@playwright/test';
import { waitTestEvent } from '../helpers';
import type { FormTestEvent } from '@/lib/test/test-events';

/** The profile page (F134): the person and their handle, their notification token and the alarms switch. */
export class ProfilePage {
  readonly root: Locator;
  readonly heading: Locator;
  readonly avatar: Locator;
  readonly name: Locator;
  readonly handle: Locator;
  readonly tokenState: Locator;
  readonly tokenField: Locator;
  readonly save: Locator;
  readonly clear: Locator;
  readonly tokenProgress: Locator;
  readonly tokenError: Locator;
  readonly alarms: Locator;

  constructor(private readonly page: Page) {
    this.root = page.getByTestId('profile');
    this.heading = this.root.getByRole('heading');
    this.avatar = this.root.locator('.avatar');
    this.name = page.getByTestId('profile.name');
    this.handle = page.getByTestId('profile.handle');
    this.tokenState = page.getByTestId('profile.token.state');
    this.tokenField = page.getByTestId('profile.token.field');
    this.save = page.getByTestId('profile.token.save');
    this.clear = page.getByTestId('profile.token.clear');
    this.tokenProgress = page.getByTestId('profile.token.progress');
    this.tokenError = page.getByTestId('profile.token.error');
    this.alarms = page.getByTestId('profile.alarms');
  }

  /** Types `token` and saves it; returns once the save has ended, as `outcome` expects, its one-shot sent or refused. */
  async saveToken(token: string, outcome: 'success' | 'error' = 'success'): Promise<void> {
    const ended = this.formEvent('people.notification-token', outcome);
    await this.tokenField.fill(token);
    await this.save.click();
    await ended;
  }

  /** Clears the token; returns once the page reads the person again, no token set. */
  async clearToken(): Promise<void> {
    const ended = this.formEvent('people.notification-token.clear', 'success');
    await this.clear.click();
    await ended;
  }

  /** Turns the alarms switch; returns once the page reads the person again, the switch turned. */
  async turnAlarms(): Promise<void> {
    const ended = this.formEvent('people.alarms', 'success');
    await this.alarms.click();
    await ended;
  }

  private formEvent(formId: string, phase: 'success' | 'error'): Promise<FormTestEvent> {
    // A save's one-shot is a task the backend runs: the bridge can take long to answer.
    return waitTestEvent<FormTestEvent>(this.page, 'form', (event) => event.formId === formId && event.phase === phase, 30_000);
  }
}

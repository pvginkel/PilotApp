import type { Locator, Page } from '@playwright/test';

/** The profile page (F134): the person and their handle. */
export class ProfilePage {
  readonly root: Locator;
  readonly heading: Locator;
  readonly avatar: Locator;
  readonly name: Locator;
  readonly handle: Locator;

  constructor(page: Page) {
    this.root = page.getByTestId('profile');
    this.heading = this.root.getByRole('heading');
    this.avatar = this.root.locator('.avatar');
    this.name = page.getByTestId('profile.name');
    this.handle = page.getByTestId('profile.handle');
  }
}

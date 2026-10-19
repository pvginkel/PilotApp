import type { Locator, Page } from '@playwright/test';

/** The handle step at a first sign-in (F137): what it says, the field and Choose. */
export class HandleStepPage {
  readonly root: Locator;
  readonly heading: Locator;
  readonly field: Locator;
  readonly choose: Locator;

  constructor(page: Page) {
    this.root = page.getByTestId('people.handle-step');
    this.heading = this.root.getByRole('heading');
    this.field = page.getByTestId('people.handle-step.field');
    this.choose = page.getByTestId('people.handle-step.choose');
  }
}

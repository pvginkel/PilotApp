/**
 * Domain-specific test fixtures.
 * App-owned — extends infrastructure fixtures with domain page objects.
 *
 * `people` signs the spec in as a fresh person, `shell` is the frame every screen sits in,
 * `handleStep` and `profile` the person's own pages.
 */

/* eslint-disable react-hooks/rules-of-hooks */
import { infrastructureFixtures } from './fixtures-infrastructure';
import { HandleStepPage } from './page-objects/handle-step-page';
import { ProfilePage } from './page-objects/profile-page';
import { ShellPage } from './page-objects/shell-page';
import { People } from './people';

interface DomainFixtures {
  people: People;
  shell: ShellPage;
  handleStep: HandleStepPage;
  profile: ProfilePage;
}

export const test = infrastructureFixtures.extend<DomainFixtures>({
  people: async ({ page, auth, backendUrl }, use) => {
    await use(new People(page, auth, backendUrl));
  },
  shell: async ({ page }, use) => {
    await use(new ShellPage(page));
  },
  handleStep: async ({ page }, use) => {
    await use(new HandleStepPage(page));
  },
  profile: async ({ page }, use) => {
    await use(new ProfilePage(page));
  },
});

export type { InfrastructureFixtures } from './fixtures-infrastructure';
export { expect } from '@playwright/test';

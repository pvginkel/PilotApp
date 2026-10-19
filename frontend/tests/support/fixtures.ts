/**
 * Domain-specific test fixtures.
 * App-owned — extends infrastructure fixtures with domain page objects.
 *
 * `people` signs the spec in as a fresh person, `shell` is the frame every screen sits in.
 */

/* eslint-disable react-hooks/rules-of-hooks */
import { infrastructureFixtures } from './fixtures-infrastructure';
import { ShellPage } from './page-objects/shell-page';
import { People } from './people';

interface DomainFixtures {
  people: People;
  shell: ShellPage;
}

export const test = infrastructureFixtures.extend<DomainFixtures>({
  people: async ({ page, auth, backendUrl }, use) => {
    await use(new People(page, auth, backendUrl));
  },
  shell: async ({ page }, use) => {
    await use(new ShellPage(page));
  },
});

export type { InfrastructureFixtures } from './fixtures-infrastructure';
export { expect } from '@playwright/test';

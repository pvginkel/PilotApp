/**
 * Domain-specific test fixtures.
 * App-owned — extends infrastructure fixtures with domain page objects.
 *
 * `people` signs the spec in as a fresh person, `projects` puts projects on the record, `links` sets
 * what links in text, `shell` is the frame every screen sits in, `handleStep` and `profile` the
 * person's own pages, `projectList` the side column's list.
 */

/* eslint-disable react-hooks/rules-of-hooks */
import { infrastructureFixtures } from './fixtures-infrastructure';
import { Links } from './links';
import { HandleStepPage } from './page-objects/handle-step-page';
import { ProfilePage } from './page-objects/profile-page';
import { ProjectListPage } from './page-objects/project-list-page';
import { ShellPage } from './page-objects/shell-page';
import { People } from './people';
import { Projects } from './projects';

interface DomainFixtures {
  people: People;
  projects: Projects;
  links: Links;
  shell: ShellPage;
  handleStep: HandleStepPage;
  profile: ProfilePage;
  projectList: ProjectListPage;
}

export const test = infrastructureFixtures.extend<DomainFixtures>({
  people: async ({ page, auth, backendUrl }, use) => {
    await use(new People(page, auth, backendUrl));
  },
  projects: async ({ page, backendUrl }, use) => {
    await use(new Projects(page, backendUrl));
  },
  links: async ({ page, backendUrl }, use) => {
    const links = new Links(page, backendUrl);
    await use(links);
    await links.set({});
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
  projectList: async ({ page }, use) => {
    await use(new ProjectListPage(page));
  },
});

export type { InfrastructureFixtures } from './fixtures-infrastructure';
export { expect } from '@playwright/test';

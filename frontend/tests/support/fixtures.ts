/**
 * Domain-specific test fixtures.
 * App-owned — extends infrastructure fixtures with domain page objects.
 *
 * `people` signs the spec in as a fresh person, `projects` puts projects on the record, `links` sets
 * what links in text, `controller` drives the worker's fake controller, `shell` is the frame every
 * screen sits in, `handleStep` and `profile` the person's own pages, `projectList` the side column's
 * list, `projectHead` a project's head, `timeline` its timeline, `overlay` the overlay over it,
 * `sessionLog` a work item's session log in it, `panel` the side panel beside it, `chat` its Chat tab,
 * `chats` puts a project's chats in the store's fake environment and sends their messages, and
 * `bridge` adds registrations to the worker's fake notification bridge and reads what they show.
 * `conditions`, the worker's, reads what the gold bar reads.
 */

/* eslint-disable react-hooks/rules-of-hooks */
import { Chats } from './chats';
import { Conditions, Controller } from './controller';
import { infrastructureFixtures } from './fixtures-infrastructure';
import { Links } from './links';
import { NotificationBridge } from './notification-bridge';
import { ChatPage } from './page-objects/chat-page';
import { HandleStepPage } from './page-objects/handle-step-page';
import { OverlayPage } from './page-objects/overlay-page';
import { PanelPage } from './page-objects/panel-page';
import { ProfilePage } from './page-objects/profile-page';
import { ProjectHeadPage } from './page-objects/project-head-page';
import { ProjectListPage } from './page-objects/project-list-page';
import { SessionLogPage } from './page-objects/session-log-page';
import { ShellPage } from './page-objects/shell-page';
import { TimelinePage } from './page-objects/timeline-page';
import { People } from './people';
import { Projects } from './projects';

interface DomainFixtures {
  people: People;
  projects: Projects;
  links: Links;
  controller: Controller;
  shell: ShellPage;
  handleStep: HandleStepPage;
  profile: ProfilePage;
  projectList: ProjectListPage;
  projectHead: ProjectHeadPage;
  timeline: TimelinePage;
  overlay: OverlayPage;
  sessionLog: SessionLogPage;
  panel: PanelPage;
  chat: ChatPage;
  definitionChat: ChatPage;
  chats: Chats;
  bridge: NotificationBridge;
}

interface DomainWorkerFixtures {
  conditions: Conditions;
}

export const test = infrastructureFixtures.extend<DomainFixtures, DomainWorkerFixtures>({
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
  controller: async ({ page, backendUrl, conditions }, use) => {
    const controller = new Controller(page, backendUrl, conditions);
    await use(controller);
    await controller.restore();
  },
  conditions: [
    async ({ playwright, _serviceManager }, use) => {
      const conditions = await Conditions.open(playwright, _serviceManager.backendUrl);
      // The backend opens its fleet stream before it listens, so the outage holds from that first
      // failed open until the stream reconnects.
      await conditions.outage(false);
      await use(conditions);
      await conditions.dispose();
    },
    { scope: 'worker', auto: true },
  ],
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
  projectHead: async ({ page }, use) => {
    await use(new ProjectHeadPage(page));
  },
  timeline: async ({ page }, use) => {
    await use(new TimelinePage(page));
  },
  overlay: async ({ page }, use) => {
    await use(new OverlayPage(page));
  },
  sessionLog: async ({ page }, use) => {
    await use(new SessionLogPage(page));
  },
  panel: async ({ page }, use) => {
    await use(new PanelPage(page));
  },
  chat: async ({ page }, use) => {
    await use(new ChatPage(page));
  },
  definitionChat: async ({ page }, use) => {
    await use(new ChatPage(page, 'feed'));
  },
  chats: async ({ page, backendUrl, controller, playwright }, use) => {
    const chats = new Chats(page, backendUrl, controller, playwright);
    await use(chats);
    await chats.dispose();
  },
  bridge: async ({ page, backendUrl }, use) => {
    const bridge = new NotificationBridge(page, backendUrl);
    await use(bridge);
    await bridge.restore();
  },
});

export type { InfrastructureFixtures } from './fixtures-infrastructure';
export { expect } from '@playwright/test';

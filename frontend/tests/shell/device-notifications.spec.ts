/**
 * A device's notifications (F94.1 to F94.3, F142): the service worker shows each push under its
 * `tag`, an alert renotifying and an update replacing silently, silent too where nothing stands
 * under its tag any more; and the app closes them where it opens, nothing being dismissed by push:
 * a page of a project closes the project's notification as it comes to show the project, and any
 * page of Pilot the alarms', on a fresh load and on coming back to the foreground. Run in
 * Chromium's full build with the notifications permission granted, where a push shows.
 */

import { randomUUID } from 'crypto';
import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import type { Push } from '../support/device';
import { makeUnique } from '../support/helpers';
import { projectAddress } from '../support/projects';

test.use({ channel: 'chromium', permissions: ['notifications'] });

/** The `tag` every person's alarms are pushed under. */
const ALARMS = 'alarms';

function pushUnder(page: Page, tag: string, change: Partial<Push> = {}): Push {
  return { title: 'Tents', body: 'Which tent?, +1', tag, url: new URL(`/projects/${tag}`, page.url()).href, renotify: true, ...change };
}

test.describe("A device's notifications", () => {
  test.describe('the service worker', () => {
    test.beforeEach(async ({ people, shell }) => {
      await people.signIn();
      await shell.open('/profile');
    });

    test('shows a push under its tag, an alert renotifying', async ({ page, device }) => {
      const push = pushUnder(page, randomUUID());

      await device.deliver(push);

      await expect
        .poll(() => device.notifications())
        .toEqual([
          {
            title: push.title,
            body: push.body,
            tag: push.tag,
            renotify: true,
            silent: false,
            icon: new URL('/icon-192.png', page.url()).href,
            url: push.url,
          },
        ]);
    });

    test('an update replaces the notification under its tag, silently', async ({ page, device }) => {
      const tag = randomUUID();
      await device.deliver(pushUnder(page, tag));
      await expect.poll(() => device.tags()).toEqual([tag]);

      await device.deliver(pushUnder(page, tag, { body: 'Which stove?', renotify: false }));

      await expect
        .poll(() => device.notifications())
        .toEqual([expect.objectContaining({ tag, body: 'Which stove?', renotify: false, silent: true })]);
    });

    test('an update shows silently where nothing stands under its tag any more', async ({ page, device }) => {
      const tag = randomUUID();
      await device.deliver(pushUnder(page, tag));
      await expect.poll(() => device.tags()).toEqual([tag]);
      // Swiped away.
      await page.evaluate(async () => (await (await navigator.serviceWorker.ready).getNotifications()).forEach((each) => each.close()));
      await expect.poll(() => device.tags()).toEqual([]);

      await device.deliver(pushUnder(page, tag, { body: 'Which stove?', renotify: false }));

      await expect
        .poll(() => device.notifications())
        .toEqual([expect.objectContaining({ tag, body: 'Which stove?', renotify: false, silent: true })]);
    });

    test('a push under another tag stands beside the first', async ({ page, device }) => {
      const [first, second] = [randomUUID(), randomUUID()];
      await device.deliver(pushUnder(page, first));
      await device.deliver(pushUnder(page, second));

      await expect.poll(() => device.tags()).toEqual([first, second].sort());
    });
  });

  test.describe('the closing', () => {
    test("a page of a project closes the project's notification as it comes to show it, and no other", async ({ page, people, projects, shell, projectList, device }) => {
      const me = await people.signIn();
      const name = makeUnique('Opened');
      const opened = await projects.make({ name, members: [me.handle!] });
      const other = await projects.make({ name: makeUnique('Other'), members: [me.handle!] });
      await shell.open('/profile');
      for (const tag of [opened, other, ALARMS]) await device.deliver(pushUnder(page, tag));
      await expect.poll(() => device.tags()).toEqual([opened, other, ALARMS].sort());

      await projectList.tab(name).click();

      await expect.poll(() => device.tags()).toEqual([other, ALARMS].sort());
    });

    test("any page of Pilot closes the alarms' on a fresh load", async ({ page, people, shell, device }) => {
      await people.signIn();
      const project = randomUUID();
      await shell.open('/profile');
      for (const tag of [project, ALARMS]) await device.deliver(pushUnder(page, tag));
      await expect.poll(() => device.tags()).toEqual([project, ALARMS].sort());

      await shell.open('/profile');

      await expect.poll(() => device.tags()).toEqual([project]);
    });

    test("coming back to the foreground closes the alarms' and the project's it shows", async ({ page, people, projects, projectList, device }) => {
      const me = await people.signIn();
      const shown = await projects.make({ name: makeUnique('Shown'), members: [me.handle!] });
      const other = randomUUID();
      await projectList.open(shown);
      await device.hide();
      for (const tag of [shown, other, ALARMS]) await device.deliver(pushUnder(page, tag));
      await expect.poll(() => device.tags()).toEqual([shown, other, ALARMS].sort());

      await device.foreground();

      await expect.poll(() => device.tags()).toEqual([other]);
    });

    test("a push on a project's page just after its load stands, the page's closing of the project done before it", async ({ page, people, projects, shell, device }) => {
      const me = await people.signIn();
      const shown = await projects.make({ name: makeUnique('Shown'), members: [me.handle!] });
      const other = randomUUID();
      // The device set up before the load, so that a deliver goes as soon as the page lets it.
      await shell.open('/profile');
      await device.deliver(pushUnder(page, other));

      await shell.open(projectAddress(shown));
      await device.deliver(pushUnder(page, shown));

      await expect.poll(() => device.tags()).toEqual([shown, other].sort());
    });

    test("opening Pilot lands on the project last open, closing its notification", async ({ page, people, projects, projectList, shell, device }) => {
      const me = await people.signIn();
      const last = await projects.make({ name: makeUnique('Last'), members: [me.handle!] });
      await projectList.open(last);
      await shell.open('/profile');
      await device.deliver(pushUnder(page, last));
      await expect.poll(() => device.tags()).toEqual([last]);

      await shell.open('/');

      await expect(page).toHaveURL(new RegExp(`${projectAddress(last)}$`));
      await expect.poll(() => device.tags()).toEqual([]);
    });
  });
});

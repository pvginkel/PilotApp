/**
 * A project's notification (F94, F147; `database.md` assertions 313 and 314): pushed to the
 * person's browser once they are offline, for an ask waiting on them they have not been shown. A
 * page of the project counts what waits there as shown, so their going offline pushes nothing for
 * it, and the next ask alerts counting it. The pushes reach the worker's fake push service, which
 * keeps them; the reconcile runs off the request, so a spec waits on what it wrote.
 */

import type { Page, Request } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

const QUESTION = '```question id=Q1\n```\n';
const PAGES = '/api/people/self/app-pages';

/** The page's away. */
function away(page: Page): Promise<Request> {
  return page.waitForRequest((request) => {
    const { pathname } = new URL(request.url());
    return request.method() === 'POST' && pathname.startsWith(`${PAGES}/`) && pathname.endsWith('/away');
  });
}

test.describe("A project's notification", () => {
  test('an ask waiting on the person reaches their browser as they leave Pilot', async ({ page, people, projects, shell, profile, browserPush, device }) => {
    await browserPush.install();
    const me = await people.signIn();
    const name = makeUnique('Lake');
    const projectId = await projects.makeWithSession({ members: [me.handle!], name });
    const question = await projects.place(projectId, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await shell.open('/profile');
    await shell.listening();
    await profile.turnDevice();

    const gone = away(page);
    await device.hide();
    await gone;

    await expect
      .poll(() => browserPush.pushes())
      .toEqual([
        {
          title: name,
          body: 'Which lake?',
          tag: projectId,
          url: expect.stringMatching(new RegExp(`/projects/${projectId}/items/${question}$`)),
          renotify: true,
          urgency: 'high',
          ttl: 86400,
        },
      ]);
  });

  test('a page of the project counts what waits there as shown, so that leaving Pilot pushes nothing for it', async ({ page, people, projects, projectList, shell, browserPush, device }) => {
    await browserPush.install();
    const me = await people.signIn();
    const name = makeUnique('Camp');
    const projectId = await projects.makeWithSession({ members: [me.handle!], name });
    const tent = await projects.place(projectId, { kind: 'question', title: 'Which tent?', text: QUESTION });
    await projectList.open(projectId);
    await shell.listening();

    // The tap is the person's input, on which the page beats with the project it shows.
    await shell.offerOn.click();

    await expect.poll(() => projects.sightings(projectId, me.handle!)).toEqual([tent]);

    const gone = away(page);
    await device.hide();
    await gone;
    await projects.place(projectId, { kind: 'question', title: 'Which site?', text: QUESTION });

    await expect.poll(async () => (await browserPush.pushes()).length).toBe(1);
    expect(await browserPush.pushes()).toEqual([
      {
        title: name,
        body: 'Which site?, +1',
        tag: projectId,
        url: expect.stringMatching(new RegExp(`/projects/${projectId}$`)),
        renotify: true,
        urgency: 'high',
        ttl: 86400,
      },
    ]);
  });
});

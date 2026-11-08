/**
 * A page's beat (F147; `database.md` assertion 312): while the page is visible and has had a key,
 * a pointer, a touch or a scroll in the last two minutes, it beats every thirty seconds and at once
 * when the project it shows changes, the project whose route it is on, by its id at each of its
 * addresses, none elsewhere; hidden, or
 * two minutes without input, it sends its away, and a page the server ended beats afresh. A person
 * at the handle step beats nothing. The page's clock is the spec's; its input waits for the page
 * to hear it (`shell.listening()`).
 */

import type { Page, Request, Response } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique, waitForUiState } from '../support/helpers';
import { projectAddress } from '../support/projects';

const PAGES = '/api/people/self/app-pages';

function pathOf(request: Request): string {
  return new URL(request.url()).pathname;
}

/** The page's next first beat, answered. */
function firstBeat(page: Page): Promise<Response> {
  return page.waitForResponse((response) => response.request().method() === 'POST' && pathOf(response.request()) === PAGES);
}

/** The page's next beat after its first, answered. */
function nextBeat(page: Page, id: string): Promise<Response> {
  return page.waitForResponse((response) => response.request().method() === 'PUT' && pathOf(response.request()) === `${PAGES}/${id}`);
}

/** The page's away for the page `id`. */
function away(page: Page, id: string): Promise<Request> {
  return page.waitForRequest((request) => request.method() === 'POST' && pathOf(request) === `${PAGES}/${id}/away`);
}

/** Every request the page sends of its beats and its away. */
function sent(page: Page): string[] {
  const requests: string[] = [];
  page.on('request', (request) => {
    if (pathOf(request).startsWith(PAGES)) requests.push(`${request.method()} ${pathOf(request)}`);
  });
  return requests;
}

/** The person's input: a pointer moved to a point it has not been at. */
let point = 0;
async function input(page: Page): Promise<void> {
  point += 1;
  await page.mouse.move(100 + point, 100 + point);
}

/** The page's id, as its first beat's answer gives it. */
async function idOf(response: Response): Promise<string> {
  expect(response.status()).toBe(201);
  return ((await response.json()) as { id: string }).id;
}

test.describe("A page's beat", () => {
  test('beats nothing until its person is active in it, then at once, with the project it shows', async ({ page, people, projects, projectList, shell }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Beaten'), members: [me.handle!] });
    await page.clock.install();
    const requests = sent(page);
    await projectList.open(project);

    await page.clock.fastForward(31_000);
    expect(requests).toEqual([]);

    const first = firstBeat(page);
    await shell.listening();
    await input(page);
    expect((await first).request().postDataJSON()).toEqual({ project_id: project });
  });

  test('beats every thirty seconds while its person is active', async ({ page, people, projects, projectList, shell }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Steady'), members: [me.handle!] });
    await page.clock.install();
    await projectList.open(project);
    const first = firstBeat(page);
    await shell.listening();
    await input(page);
    const id = await idOf(await first);

    const beat = nextBeat(page, id);
    await page.clock.fastForward(30_000);
    const answered = await beat;
    expect(answered.status()).toBe(204);
    expect(answered.request().postDataJSON()).toEqual({ project_id: project });
  });

  test('beats at once when the project it shows changes', async ({ page, people, projects, projectList, shell }) => {
    const me = await people.signIn();
    const here = await projects.make({ name: makeUnique('Here'), members: [me.handle!] });
    const thereName = makeUnique('There');
    const there = await projects.make({ name: thereName, members: [me.handle!] });
    await page.clock.install();
    await projectList.open(here);
    const first = firstBeat(page);
    await shell.listening();
    await input(page);
    const id = await idOf(await first);
    const tab = projectList.tab(thereName);
    await expect(tab).toBeVisible();
    // The page's clock stands still from here, so no beat of its thirty seconds comes.
    // eslint-disable-next-line no-restricted-properties -- The page's own clock, read to pause it.
    await page.clock.pauseAt(await page.evaluate(() => Date.now() + 1_000));

    const beat = nextBeat(page, id);
    await tab.click();
    expect((await beat).request().postDataJSON()).toEqual({ project_id: there });
  });

  for (const form of ['a draft’s name', 'a slug', 'an id'] as const) {
    test(`shows its project by the project’s id at ${form}`, async ({ page, people, projects, shell }) => {
      const me = await people.signIn();
      const { id, folder } =
        form === 'a draft’s name'
          ? await projects.makeDraft({ members: [me.handle!] })
          : { id: await projects.make({ name: makeUnique('Open'), members: [me.handle!] }), folder: null };
      await page.goto(form === 'an id' ? `/projects/${id}` : form === 'a slug' ? projectAddress(id) : `/projects/${folder}`);
      await waitForUiState(page, 'project.head', 'ready');
      const first = firstBeat(page);
      await shell.listening();
      await input(page);
      expect((await first).request().postDataJSON()).toEqual({ project_id: id });
    });
  }

  test('shows no project on a page of none', async ({ page, people, shell }) => {
    await people.signIn();
    await shell.open('/profile');
    const first = firstBeat(page);
    await shell.listening();
    await input(page);
    expect((await first).request().postDataJSON()).toEqual({ project_id: null });
  });

  test('sends its away as it hides, and beats afresh as it comes back', async ({ page, people, shell, device }) => {
    await people.signIn();
    await shell.open('/profile');
    const first = firstBeat(page);
    await shell.listening();
    await input(page);
    const id = await idOf(await first);

    const gone = away(page, id);
    await device.hide();
    await gone;

    const again = firstBeat(page);
    await device.foreground();
    expect(await idOf(await again)).not.toBe(id);
  });

  test('sends its away after two minutes without input, and beats afresh at the next', async ({ page, people, shell }) => {
    await people.signIn();
    await page.clock.install();
    await shell.open('/profile');
    const first = firstBeat(page);
    await shell.listening();
    await input(page);
    const id = await idOf(await first);

    const gone = away(page, id);
    await page.clock.fastForward(120_000);
    await gone;

    const again = firstBeat(page);
    await input(page);
    expect(await idOf(await again)).not.toBe(id);
  });

  test('beats afresh once the server has ended its page', async ({ page, people, shell, backendUrl }) => {
    await people.signIn();
    await page.clock.install();
    await shell.open('/profile');
    const first = firstBeat(page);
    await shell.listening();
    await input(page);
    const id = await idOf(await first);
    const ended = await page.request.post(`${backendUrl}${PAGES}/${id}/away`);
    expect(ended.status()).toBe(204);

    const refused = nextBeat(page, id);
    const again = firstBeat(page);
    await page.clock.fastForward(30_000);
    expect((await refused).status()).toBe(404);
    expect(await idOf(await again)).not.toBe(id);
  });

  test('beats nothing at the handle step', async ({ page, people, shell }) => {
    await people.firstSignIn();
    await page.clock.install();
    const requests = sent(page);
    await shell.open();

    await page.mouse.move(100, 100);
    await page.clock.fastForward(31_000);
    expect(requests).toEqual([]);
  });
});

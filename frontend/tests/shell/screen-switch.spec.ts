/**
 * A switch that never blanks the screen (H5): the router keeps the screen it leaves until the
 * project's head and its timeline are read, or a draft's chats, and until a document's tab has its
 * document; the project's tab reads its project's on hover or touch, so that its switch waits for
 * nothing; and a wait that lasts 200 ms shows the loading bar, under the top bar, on a phone at the
 * page's top, until the screen comes. What the page shows is read at each change of its DOM, by the
 * page's clock, so that a screen drawn between two reads shows in the record.
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique, waitForUiState } from '../support/helpers';
import { slowNetwork } from '../support/network';

const WORDS = Array.from({ length: 160 }, (_, index) => `word${index}`).join(' ');
/** A document long enough to be a card on the timeline, whose Open opens it. */
const card = (title: string) => `---\ntitle: ${title}\n---\n\n${WORDS}\n`;
const PHONE = { width: 390, height: 844 };

/** What the page shows at a change of its DOM. */
interface Shown {
  /** The head's name, none without a head. */
  name: string | null;
  /** The timeline's items. */
  items: number;
  /** A document's tab drawn without its title. */
  untitled: boolean;
  /** The new project's screen: a head with no members. */
  fresh: boolean;
  /** The loading bar. */
  bar: boolean;
  /** When, by the page's clock. */
  at: number;
}

interface Watched {
  shown: Shown[];
  /** When the page was last pressed, by its clock. */
  pressed: number;
  /** Each read the page made, by its path, and when its answer had come. */
  reads: { path: string; end: number }[];
}

/** What the page shows from the call on, each change of it, when it is pressed and what it reads; read by the answer. */
async function watch(page: Page): Promise<() => Promise<Watched>> {
  await page.evaluate(() => {
    const record: Watched = { shown: [], pressed: Number.NaN, reads: [] };
    const one = (testId: string) => document.querySelector(`[data-testid="${testId}"]`);
    const look = () => {
      const shown = {
        name: one('project.name')?.textContent ?? null,
        items: document.querySelectorAll('[data-testid="timeline.item"]').length,
        untitled: Array.from(document.querySelectorAll('[data-testid="overlay"]')).some((tab) => !tab.querySelector('[data-testid="overlay.title"]')?.textContent),
        fresh: one('project.head') !== null && one('project.members') === null,
        bar: one('shell.loading') !== null,
      };
      const last = record.shown.at(-1);
      if (last === undefined || (Object.keys(shown) as (keyof typeof shown)[]).some((key) => last[key] !== shown[key])) {
        record.shown.push({ ...shown, at: performance.now() });
      }
    };
    look();
    new MutationObserver(look).observe(document.body, { subtree: true, childList: true, characterData: true });
    window.addEventListener('pointerdown', () => (record.pressed = performance.now()), { capture: true });
    new PerformanceObserver((entries) => {
      for (const entry of entries.getEntries() as PerformanceResourceTiming[]) record.reads.push({ path: new URL(entry.name).pathname, end: entry.responseEnd });
    }).observe({ type: 'resource' });
    (window as unknown as { record: Watched }).record = record;
  });
  return () => page.evaluate(() => (window as unknown as { record: Watched }).record);
}

/** The head's name and the timeline's items, each change of them in order. */
const screens = (shown: Shown[]) =>
  shown
    .map(({ name, items }) => [name, items])
    .filter((each, index, all) => index === 0 || each[0] !== all[index - 1][0] || each[1] !== all[index - 1][1]);

/** The project's head and its timeline, once both are read. */
const projectRead = (page: Page, id: string) =>
  Promise.all(
    [`/api/projects/${id}`, `/api/projects/${id}/timeline`].map((path) =>
      page.waitForResponse((response) => response.request().method() === 'GET' && new URL(response.url()).pathname === path),
    ),
  );

test.describe('A switch of screens', () => {
  test('to a project not read yet keeps the screen it leaves, its head and timeline, until the project’s head and timeline are read', async ({
    page,
    people,
    projects,
    projectList,
    timeline,
    projectHead,
  }) => {
    const me = await people.signIn();
    const a = makeUnique('A');
    const aId = await projects.makeWithSession({ name: a, members: [me.handle!] });
    await projects.place(aId, { kind: 'document', title: 'At A', text: card('At A') });
    const b = makeUnique('B');
    const bId = await projects.makeWithSession({ name: b, members: [me.handle!] });
    const atB = await projects.place(bId, { kind: 'document', title: 'At B', text: card('At B') });
    await timeline.open(aId);
    await expect(timeline.items).toHaveCount(1);

    const record = await watch(page);
    await projectList.tab(b).click();
    await expect(projectHead.name).toHaveText(b);
    await expect(timeline.item(atB).root).toBeVisible();

    expect(screens((await record()).shown)).toEqual([
      [a, 1],
      [b, 1],
    ]);
  });

  test('that waits 200 ms shows the loading bar under the top bar, across the page, the screen left standing until the project’s comes', async ({
    page,
    people,
    projects,
    projectList,
    timeline,
    projectHead,
    shell,
  }) => {
    const me = await people.signIn();
    const a = makeUnique('A');
    const aId = await projects.makeWithSession({ name: a, members: [me.handle!] });
    await projects.place(aId, { kind: 'document', title: 'At A', text: card('At A') });
    const b = makeUnique('B');
    const bId = await projects.makeWithSession({ name: b, members: [me.handle!] });
    await projects.place(bId, { kind: 'document', title: 'At B', text: card('At B') });
    await timeline.open(aId);
    await expect(shell.loading).toHaveCount(0);

    const record = await watch(page);
    const restore = await slowNetwork(page, 800);
    await projectList.tab(b).click();
    await expect(shell.loading).toBeVisible();
    await expect(shell.loading).toHaveAttribute('role', 'progressbar');
    await expect(projectHead.name).toHaveText(a);
    const bar = (await shell.loading.boundingBox())!;
    const top = (await shell.topBar.boundingBox())!;
    expect([bar.x, bar.width, bar.height]).toEqual([0, page.viewportSize()!.width, 3]);
    expect(bar.y).toBeCloseTo(top.y + top.height, 0);

    await expect(projectHead.name).toHaveText(b);
    await expect(shell.loading).toHaveCount(0);
    await restore();

    const { shown, pressed } = await record();
    expect(screens(shown)).toEqual([
      [a, 1],
      [b, 1],
    ]);
    // Not before the wait has lasted 200 ms, over the screen left.
    const barred = shown.find((each) => each.bar)!;
    expect(barred.at - pressed).toBeGreaterThanOrEqual(200);
    expect(barred.name).toBe(a);
  });

  test('to a project whose tab was under the mouse waits for nothing: the tab read its head and timeline', async ({
    page,
    people,
    projects,
    projectList,
    timeline,
    projectHead,
  }) => {
    const me = await people.signIn();
    const aId = await projects.makeWithSession({ name: makeUnique('A'), members: [me.handle!] });
    const b = makeUnique('B');
    const bId = await projects.makeWithSession({ name: b, members: [me.handle!] });
    const atB = await projects.place(bId, { kind: 'document', title: 'At B', text: card('At B') });
    await timeline.open(aId);

    const read = projectRead(page, bId);
    await projectList.tab(b).hover();
    await read;

    // Any read the switch waited for would take two seconds.
    const record = await watch(page);
    const restore = await slowNetwork(page, 2000);
    await projectList.tab(b).click();
    await expect(projectHead.name).toHaveText(b);
    await expect(timeline.item(atB).root).toBeVisible();
    const { shown, pressed } = await record();
    await restore();
    expect(shown.find((each) => each.name === b)!.at - pressed).toBeLessThan(2000);
  });

  test('to a document keeps the screen it leaves until the document is read: no tab stands without its document', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    docTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Tabs'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: card('The trip') });
    const route = await projects.place(id, { kind: 'document', title: 'The route', text: card('The route') });
    await timeline.open(id);

    const record = await watch(page);
    await timeline.item(trip).card.open.click();
    await expect(overlay.title).toHaveText('The trip');
    await docTabs.first.click();
    await expect(overlay.root).toHaveCount(0);
    await timeline.item(route).card.open.click();
    await expect(overlay.title).toHaveText('The route');

    const { shown } = await record();
    expect(shown.filter((each) => each.untitled)).toEqual([]);
  });

  test('from a new project to its draft, at its first send, keeps the new project’s screen until the draft’s chats are read', async ({
    page,
    people,
    projects,
    projectList,
    controller,
    definitionChat,
    chats,
  }) => {
    await people.signIn();
    await page.goto('/');
    await waitForUiState(page, 'projects.list', 'ready');
    await projectList.newProject.click();
    await expect(definitionChat.empty).toBeVisible();

    const opened = await chats.openingNew();
    await definitionChat.field.fill('Let us plan the summer trip.');
    const record = await watch(page);
    const created = projectList.created();
    await definitionChat.send.click();
    const id = (await created).fields!.project as string;
    const head = await projects.head(id);
    await expect(page).toHaveURL(`/projects/${head.address}`);
    await expect(definitionChat.messageTexts).toHaveText(['Let us plan the summer trip.']);
    const session = await opened(head.address);

    const { shown, reads } = await record();
    const left = shown.find((each) => !each.fresh)!.at;
    const read = reads.find((each) => each.path === `/api/projects/${id}/chats`)!.end;
    expect(left).toBeGreaterThanOrEqual(read);
    await controller.finish(chats.store, session, 'success', 'Noted.');
  });
});

test.describe('A switch of screens on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('to a project whose tab was touched reads its head and timeline from the touch; a wait of 200 ms shows the loading bar at the page’s top', async ({
    page,
    people,
    projects,
    projectList,
    timeline,
    projectHead,
    shell,
  }) => {
    const me = await people.signIn();
    const a = makeUnique('A');
    const aId = await projects.makeWithSession({ name: a, members: [me.handle!] });
    const b = makeUnique('B');
    const bId = await projects.makeWithSession({ name: b, members: [me.handle!] });
    const c = makeUnique('C');
    await projects.makeWithSession({ name: c, members: [me.handle!] });
    await timeline.open(aId);
    await shell.drawerToggle.click();
    await expect(shell.side).toBeVisible();

    const read = projectRead(page, bId);
    await projectList.tab(b).dispatchEvent('touchstart');
    await read;

    const restore = await slowNetwork(page, 800);
    await projectList.tab(c).tap();
    await expect(shell.loading).toBeVisible();
    await expect(projectHead.name).toHaveText(a);
    const bar = (await shell.loading.boundingBox())!;
    const app = (await shell.app.boundingBox())!;
    expect([bar.x, bar.width, bar.height]).toEqual([0, PHONE.width, 3]);
    expect(bar.y).toBeCloseTo(app.y, 0);
    await expect(projectHead.name).toHaveText(c);
    await expect(shell.loading).toHaveCount(0);
    await restore();
  });
});

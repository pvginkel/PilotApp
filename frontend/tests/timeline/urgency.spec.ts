/**
 * Urgent items (F10.1, F10.2): tinted where they were placed, the first open one that is not
 * Pilot's with a banner pinned to the top, "+<n>" on it for the others, whose Show scrolls to that
 * item and flashes it; and the "N open above" chip (F11), counting the items that can be acted on
 * scrolled out above and scrolling to the nearest.
 */

import type { Locator } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique, makeUniqueToken } from '../support/helpers';
import type { Projects } from '../support/projects';

const QUESTION = '```question id=Q1\n```\n';
const URGENT_QUESTION = `---\nurgent: true\n---\n\n${QUESTION}`;
const NOTICE = 'A notice that takes\n\na few lines\n\nof the timeline.\n';
const PITCH_PATH = '/work/Example/pitch.md';
const URGENT_PITCH = `---\nurgent: true\n---\n\n# Where do we pitch?\n\nThe lake or the hill.\n\n${QUESTION}`;

// An invented line in `claude`'s shape (backend/tests/fixtures/raw/).
const SAID = JSON.stringify({
  type: 'assistant',
  message: { id: 'msg_wrote', content: [{ type: 'text', text: 'The pitch is written and registered.' }] },
  parent_tool_use_id: null,
  session_id: '5b8f0c2e-91d4-4a6b-8e37-c0d2f41a9e65',
});

/** The banner's parts' boxes, left to right: its title, its "+<n>" where it has one, and Show. */
async function partsOf(banner: Locator) {
  const box = async (testId: string) => (await banner.getByTestId(testId).boundingBox())!;
  const more = (await banner.getByTestId('timeline.banner.more').count()) === 0 ? null : await box('timeline.banner.more');
  return { whole: (await banner.boundingBox())!, title: await box('timeline.banner.title'), more, show: await box('timeline.banner.show') };
}

test.describe('An urgent item', () => {
  test('is tinted where it was placed, one banner pinned to the top for the first one open, “+n” on it for the others', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Urgent'), members: [me.handle!] });
    const calm = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    const storm = await projects.place(id, { kind: 'question', title: 'Storm coming?', text: URGENT_QUESTION });
    const flood = await projects.place(id, { kind: 'notice', title: 'Flood', text: '---\nurgent: true\n---\n\nThe river rises.\n' });
    const answered = await projects.place(id, { kind: 'question', title: 'Answered already', text: URGENT_QUESTION });
    await projects.answer(answered, 'Q1', 'Yes');
    const drought = await projects.place(id, { kind: 'question', title: 'Drought?', text: URGENT_QUESTION });
    await timeline.open(id);

    await expect(timeline.item(storm).root).toHaveClass(/\burgent\b/);
    await expect(timeline.item(flood).root).toHaveClass(/\burgent\b/);
    await expect(timeline.item(calm).root).not.toHaveClass(/\burgent\b/);
    await expect(timeline.item(answered).line).toBeVisible();
    await expect(timeline.item(answered).root).not.toHaveClass(/\burgent\b/);

    await expect(timeline.banners).toHaveCount(1);
    expect(await timeline.bannerItems()).toEqual([storm]);
    // No dot on either side of the title.
    await expect(timeline.banner(storm)).toHaveText(/^Urgent\s*Storm coming\?\s*\+2\s*Show\s*$/);
    await expect(timeline.bannerMore).toHaveText('+2');
    await expect(timeline.bannerMore).toHaveAttribute('aria-label', '2 more urgent items');

    // The title has the room the banner's other parts leave, and Show room on its left.
    const { whole, title, more, show } = await partsOf(timeline.banner(storm));
    expect(more!.x - (title.x + title.width)).toBeGreaterThanOrEqual(10);
    expect(show.x - (more!.x + more!.width)).toBeGreaterThanOrEqual(16);
    expect(title.width).toBeGreaterThan(whole.width / 2);
    // "+n" moves none of the bar's words off its middle: they stand as far from its top as from its bottom.
    expect(await timeline.bannerMore.evaluate((element) => getComputedStyle(element).marginTop)).toBe('0px');
    expect(Math.abs(title.y - whole.y - (whole.y + whole.height - (title.y + title.height)))).toBeLessThanOrEqual(1);

    const feed = (await timeline.root.boundingBox())!;
    const banners = (await timeline.root.getByTestId('timeline.banners').boundingBox())!;
    expect(Math.abs(banners.y - feed.y)).toBeLessThan(1);
    await timeline.scrollToTop();
    expect(Math.abs((await timeline.root.getByTestId('timeline.banners').boundingBox())!.y - feed.y)).toBeLessThan(1);

    // The first one answered, the banner is the next one's, live.
    await projects.answer(storm, 'Q1', 'Inside');
    await expect(timeline.banner(flood)).toHaveText(/^Urgent\s*Flood\s*\+1\s*Show\s*$/);
    expect(await timeline.bannerItems()).toEqual([flood]);
    await expect(timeline.bannerMore).toHaveAttribute('aria-label', '1 more urgent item');

    // The last one left has no “+n”, and Show the same room after its title.
    await projects.answer(drought, 'Q1', 'No');
    await expect(timeline.banner(flood)).toHaveText(/^Urgent\s*Flood\s*Show\s*$/);
    await expect(timeline.bannerMore).toHaveCount(0);
    const alone = await partsOf(timeline.banner(flood));
    expect(alone.show.x - (alone.title.x + alone.title.width)).toBeGreaterThanOrEqual(16);
  });

  test('has no banner while Pilot works on it, and its banner once Pilot’s pass on it ends', async ({
    chats,
    controller,
    deploymentSse,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Passed'), members: [me.handle!] });
    const work = await projects.startWork(id, { title: 'Choosing the pitch', brief: 'Choose the pitch.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(id, work)).state).toBe('running');
    const { id: environment } = await projects.environment(id, work);
    await controller.putFile(environment, PITCH_PATH, URGENT_PITCH);
    const pitch = await projects.register(work, PITCH_PATH);
    await timeline.open(id);
    await deploymentSse.ensureConnected();
    const item = timeline.item(pitch);

    // The run's turn ends, and the pass over its document runs: the document is urgent, and Pilot's.
    const pass = await chats.pass(id);
    await controller.play(environment, 'claude-1', [SAID]);
    await controller.finish(environment, 'claude-1');
    await pass.running();
    await expect(item.pilots.root).toHaveText('Pre-ruling');
    await expect(item.root).toHaveAttribute('data-state', 'pilots');
    const passing = await projects.item(id, pitch);
    expect(passing.urgent).toBe(true);
    expect(passing.pilots_work).not.toBeNull();
    await expect(timeline.banners).toHaveCount(0);

    await pass.end();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.root).toHaveClass(/\burgent\b/);
    await expect(timeline.banner(pitch)).toHaveText(/^Urgent\s*Where do we pitch\?\s*Show\s*$/);
  });

  test('is shown and flashed by its banner’s Show, the timeline staying there, and loses its banner once done', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Show'), members: [me.handle!] });
    const storm = await projects.place(id, { kind: 'question', title: 'Storm coming?', text: URGENT_QUESTION });
    for (let index = 0; index < 8; index += 1) {
      await projects.place(id, { kind: 'notice', title: `Notice ${index + 1}`, text: NOTICE });
    }
    await timeline.open(id);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);

    const item = timeline.item(storm);
    await expect(item.root).not.toBeInViewport();
    await expect(item.root).not.toHaveClass(/\bfresh\b/);
    await timeline.banner(storm).click();
    await expect(item.root).toHaveClass(/\bfresh\b/);
    await expect(item.root).toBeInViewport();
    await expect(item.root).not.toHaveClass(/\bfresh\b/);
    await timeline.banner(storm).click();
    await expect(item.root).toHaveClass(/\bfresh\b/);

    const arrived = await projects.place(id, { kind: 'notice', title: 'Arrived', text: NOTICE });
    await expect(timeline.item(arrived).root).toBeAttached();
    await expect(item.root).toBeInViewport();
    expect(await timeline.fromEnd()).toBeGreaterThan(100);

    await projects.answer(storm, 'Q1', 'Inside');
    await expect(item.line).toBeVisible();
    await expect(timeline.banners).toHaveCount(0);
  });

  test('is shown by Show on a timeline that does not scroll, which keeps following its end', async ({
    deploymentSse,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Fits'), members: [me.handle!] });
    const storm = await projects.place(id, { kind: 'question', title: 'Storm coming?', text: URGENT_QUESTION });
    await timeline.open(id);
    await deploymentSse.ensureConnected();
    expect(await timeline.root.evaluate((feed) => feed.scrollHeight - feed.clientHeight)).toBeLessThan(1);

    await timeline.banner(storm).click();
    await expect(timeline.item(storm).root).toHaveClass(/\bfresh\b/);

    let last = '';
    for (let index = 0; index < 8; index += 1) {
      last = await projects.place(id, { kind: 'notice', title: `Notice ${index + 1}`, text: NOTICE });
    }
    await expect(timeline.item(last).root).toBeAttached();
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
  });
});

test.describe('An urgent item’s banner on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('keeps to one line, its triangle saying Urgent alone, a long title cut at its end with room before “+n” and Show', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Narrow'), members: [me.handle!] });
    const title = 'Does the storm that comes over the lake tonight reach the camp before we strike it?';
    const storm = await projects.place(id, { kind: 'question', title, text: URGENT_QUESTION });
    await projects.place(id, { kind: 'question', title: 'Flood coming?', text: URGENT_QUESTION });
    await timeline.open(id);

    const banner = timeline.banner(storm);
    await expect(banner).toHaveText(new RegExp(`^Urgent\\s*${title.replace('?', '\\?')}\\s*\\+1\\s*Show\\s*$`));
    const { whole, title: cut, more, show } = await partsOf(banner);
    expect(whole.height).toBeLessThan(48);
    expect(await banner.getByTestId('timeline.banner.title').evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
    expect(more!.x - (cut.x + cut.width)).toBeGreaterThanOrEqual(10);
    expect(show.x - (more!.x + more!.width)).toBeGreaterThanOrEqual(16);
    expect(show.x + show.width).toBeLessThan(whole.x + whole.width);
    // The word is a screen reader's alone, and the title takes more of the banner than everything else in it.
    expect((await banner.getByText('Urgent', { exact: true }).boundingBox())!.width).toBeLessThanOrEqual(1);
    expect(cut.width).toBeGreaterThan(whole.width / 2);
  });
});

test.describe('“N open above”', () => {
  // Short enough that fourteen done lines fill more than the timeline.
  test.use({ viewport: { width: 1280, height: 600 } });

  /** Questions you answered: done lines. */
  async function answered(projects: Projects, id: string, count: number): Promise<void> {
    for (let index = 0; index < count; index += 1) {
      const ask = await projects.place(id, { kind: 'question', title: `Answered ${index + 1}`, text: QUESTION });
      await projects.answer(ask, 'Q1', 'Yes');
    }
  }

  test('counts the items to act on scrolled out above, under the head, and scrolls to the nearest', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Above'), members: [me.handle!] });
    const first = await projects.place(id, { kind: 'question', title: 'First ask', text: QUESTION });
    await answered(projects, id, 6);
    const second = await projects.place(id, { kind: 'question', title: 'Second ask', text: QUESTION });
    await answered(projects, id, 14);
    await timeline.open(id);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);

    await expect(timeline.openAbove).toHaveText('2 open above');
    const head = (await page.getByTestId('project.head').boundingBox())!;
    const chip = (await timeline.openAbove.boundingBox())!;
    expect(chip.y).toBeGreaterThanOrEqual(head.y + head.height);
    expect(chip.y).toBeLessThan(head.y + head.height + 30);

    await timeline.openAbove.click();
    await expect(timeline.item(second).root).toBeInViewport();
    await expect(timeline.openAbove).toHaveText('1 open above');
    await timeline.openAbove.click();
    await expect(timeline.item(first).root).toBeInViewport();
    await expect(timeline.openAbove).toHaveCount(0);
  });

  test('counts a notice that is not urgent, another member’s item and stopped work; never work that runs, nor a wait', async ({
    people,
    projects,
    timeline,
    waits,
  }) => {
    const ben = makeUnique('ben', 8);
    await people.other(ben, 'Ben Example');
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Acted'), members: [me.handle!, ben] });
    const notice = await projects.place(id, { kind: 'notice', title: 'The bikes are in', text: 'The bikes are in the shed.\n' });
    await answered(projects, id, 6);
    const hers = await projects.place(id, { kind: 'question', title: 'Which bike?', text: `---\nfor: ${ben}\n---\n\n${QUESTION}` });
    await answered(projects, id, 6);
    const stopped = await projects.startWork(id, { title: 'Surveying the shed', brief: 'Survey the shed.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(id, stopped)).state).toBe('running');
    expect((await projects.stop(stopped)).state).toBe('stopped');
    const going = await projects.startWork(id, { title: 'Surveying the camp', brief: 'Survey the camp.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(id, going)).state).toBe('running');
    const key = `W${makeUniqueToken(6).toUpperCase()}`;
    const wait = await waits.add(id, { kind: 'card_wait', title: 'The shed’s card', cards: [`${key}-1`], states: ['Done'] });
    await answered(projects, id, 14);
    await timeline.open(id);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);

    for (const open of [notice, hers, stopped, going, wait]) {
      await expect(timeline.item(open).root).toHaveAttribute('data-state', 'open');
      await expect(timeline.item(open).root).not.toBeInViewport();
    }
    await expect(timeline.openAbove).toHaveText('3 open above');
    await timeline.openAbove.click();
    await expect(timeline.item(stopped).root).toBeInViewport();
    await expect(timeline.openAbove).toHaveText('2 open above');
    await timeline.openAbove.click();
    await expect(timeline.item(hers).root).toBeInViewport();
    await expect(timeline.openAbove).toHaveText('1 open above');
    await timeline.openAbove.click();
    await expect(timeline.item(notice).root).toBeInViewport();
    await expect(timeline.openAbove).toHaveCount(0);
  });

  test('stays away for done lines above and for open items below', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Below'), members: [me.handle!] });
    await answered(projects, id, 20);
    const last = await projects.place(id, { kind: 'question', title: 'Last ask', text: QUESTION });
    await timeline.open(id);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    await expect(timeline.item(last).root).toBeInViewport();
    await expect(timeline.openAbove).toHaveCount(0);

    await timeline.scrollToTop();
    await expect(timeline.item(last).root).not.toBeInViewport();
    await expect(timeline.openAbove).toHaveCount(0);
  });
});

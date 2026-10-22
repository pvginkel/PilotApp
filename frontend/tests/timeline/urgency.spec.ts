/**
 * Urgent items (F10.1, F10.2): tinted where they were placed, each open one with a banner pinned to
 * the top whose Show scrolls to it and flashes it; and the "N open above" chip (F11), counting the
 * open items scrolled out above and scrolling to the nearest.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { Projects } from '../support/projects';

const QUESTION = '```question id=Q1\n```\n';
const URGENT_QUESTION = `---\nurgent: true\n---\n\n${QUESTION}`;
const NOTICE = 'A notice that takes\n\na few lines\n\nof the timeline.\n';

test.describe('An urgent item', () => {
  test('is tinted where it was placed, a banner pinned to the top for each one open, in their order', async ({
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
    await timeline.open(id);

    await expect(timeline.item(storm).root).toHaveClass(/\burgent\b/);
    await expect(timeline.item(flood).root).toHaveClass(/\burgent\b/);
    await expect(timeline.item(calm).root).not.toHaveClass(/\burgent\b/);
    await expect(timeline.item(answered).line).toBeVisible();
    await expect(timeline.item(answered).root).not.toHaveClass(/\burgent\b/);

    await expect(timeline.banners).toHaveCount(2);
    expect(await timeline.bannerItems()).toEqual([storm, flood]);
    await expect(timeline.banner(storm)).toHaveText(/^Urgent\s*·\s*Storm coming\?\s*·\s*Show\s*$/);
    await expect(timeline.banner(flood)).toHaveText(/^Urgent\s*·\s*Flood\s*·\s*Show\s*$/);

    const feed = (await timeline.root.boundingBox())!;
    const banners = (await timeline.root.getByTestId('timeline.banners').boundingBox())!;
    expect(Math.abs(banners.y - feed.y)).toBeLessThan(1);
    await timeline.scrollToTop();
    expect(Math.abs((await timeline.root.getByTestId('timeline.banners').boundingBox())!.y - feed.y)).toBeLessThan(1);
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

  test('counts the open items scrolled out above, under the head, and scrolls to the nearest', async ({
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

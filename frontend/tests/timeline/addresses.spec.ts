/**
 * A URL per item and block (F97): an item's address under its project's, a block's under its
 * item's, by their ids. Opening one scrolls the timeline to it and flashes it: a block's goes to
 * the block, a confirmation's to its card's row, and a done item's to its line; an address the
 * timeline draws nothing for leaves it at its end.
 */

import { randomUUID } from 'node:crypto';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { addressOf } from '../support/page-objects/timeline-page';
import type { Projects } from '../support/projects';

const DECISION = 'Which tent for the trip?\n\n```decision id=D1\noptions:\n  - Dome: up in five minutes\n  - Tunnel\n```\n';
const CONFIRMATION = 'The tag is cut.\n\n```decision id=C1\ntype: confirmation\nproposal: Push the release\nbecause: auto-pilot-off\n```\n';
const QUESTION = '```question id=Q1\n```\n';
const NOTICE = 'A notice that takes\n\na few lines\n\nof the timeline.\n';

/** Enough notices after what is placed that the timeline, at its end, shows none of it. */
async function notices(projects: Projects, id: string): Promise<void> {
  for (let index = 0; index < 8; index += 1) {
    await projects.place(id, { kind: 'notice', title: `Notice ${index + 1}`, text: NOTICE });
  }
}

test.describe('An item’s address', () => {
  test('opens its project’s timeline at the item, flashed, the tab current, and the timeline stays there as items arrive', async ({
    page,
    people,
    projectList,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Address');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await notices(projects, id);

    await timeline.openAt(id, decision);
    const item = timeline.item(decision);
    await expect(item.root).toHaveClass(/\bfresh\b/);
    await expect(item.root).toBeInViewport();
    await expect(item.root).not.toHaveClass(/\bfresh\b/);
    await expect.poll(() => timeline.fromEnd()).toBeGreaterThan(100);
    await expect(page).toHaveURL(addressOf(id, decision));
    await expect(projectList.tab(name)).toHaveAttribute('aria-current', 'page');
    await expect(item.block.root).not.toHaveClass(/\bflash\b/);

    const arrived = await projects.place(id, { kind: 'notice', title: 'Arrived', text: NOTICE });
    await timeline.refocus();
    await expect(timeline.item(arrived).root).toBeAttached();
    await expect(item.root).toBeInViewport();
    expect(await timeline.fromEnd()).toBeGreaterThan(100);
  });

  test('goes to the item again when it is opened with the timeline on screen, by Back', async ({
    page,
    people,
    projectList,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Back');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await notices(projects, id);
    await timeline.openAt(id, decision);
    const item = timeline.item(decision);
    await expect(item.root).toBeInViewport();
    await expect(item.root).not.toHaveClass(/\bfresh\b/);

    // The project's own address keeps the timeline where it stands.
    await projectList.tab(name).click();
    await expect(page).toHaveURL(`/projects/${id}`);
    await expect(item.root).toBeInViewport();
    await timeline.root.evaluate((feed) => feed.scrollTo({ top: feed.scrollHeight }));
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    await expect(item.root).not.toBeInViewport();

    await page.goBack();
    await expect(page).toHaveURL(addressOf(id, decision));
    await expect(item.root).toHaveClass(/\bfresh\b/);
    await expect(item.root).toBeInViewport();
  });

  test('of the opening goes to the opening and flashes its words', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Opening'), members: [me.handle!] });
    await notices(projects, id);
    const opening = (await projects.timeline(id)).items.find((item) => item.kind === 'opening')!;

    await timeline.openAt(id, opening.id);
    await expect(timeline.opening).toHaveClass(/\bfresh\b/);
    await expect(timeline.opening).toBeInViewport();
    await expect(timeline.opening).not.toHaveClass(/\bfresh\b/);
  });

  test('that the timeline draws nothing for leaves it at its end', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Nowhere'), members: [me.handle!] });
    await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await notices(projects, id);

    await timeline.openAt(id, randomUUID());
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    await expect(timeline.root.locator('.fresh, .flash')).toHaveCount(0);
  });
});

test.describe('A block’s address', () => {
  test('goes to the block and flashes it, not its item', async ({ page, people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Block'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await notices(projects, id);

    await timeline.openAt(id, decision, 'D1');
    const item = timeline.item(decision);
    await expect(item.block.root).toHaveClass(/\bflash\b/);
    await expect(item.block.root).toBeInViewport();
    await expect(item.root).not.toHaveClass(/\bfresh\b/);
    await expect(item.block.root).not.toHaveClass(/\bflash\b/);
    await expect(page).toHaveURL(addressOf(id, decision, 'D1'));
    expect(await timeline.fromEnd()).toBeGreaterThan(100);
  });

  test('of a confirmation goes to its card’s row', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Confirm'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Push it?', text: CONFIRMATION });
    await notices(projects, id);

    await timeline.openAt(id, confirmation, 'C1');
    const { confirm, root } = timeline.item(confirmation);
    await expect(confirm.root).toHaveAttribute('data-block-id', 'C1');
    await expect(confirm.root).toHaveClass(/\bflash\b/);
    await expect(confirm.root).toBeInViewport();
    await expect(root).not.toHaveClass(/\bfresh\b/);
    await expect(confirm.root).not.toHaveClass(/\bflash\b/);
  });

  test('goes to its item where the timeline draws no such block: a done item’s line, a block the item lacks', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Line'), members: [me.handle!] });
    const question = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await notices(projects, id);
    await projects.answer(question, 'Q1', 'The quiet one');

    await timeline.openAt(id, question, 'Q1');
    const line = timeline.item(question);
    await expect(line.line).toBeVisible();
    await expect(line.root).toHaveClass(/\bfresh\b/);
    await expect(line.root).toBeInViewport();

    await timeline.openAt(id, decision, 'D9');
    const item = timeline.item(decision);
    await expect(item.root).toHaveClass(/\bfresh\b/);
    await expect(item.root).toBeInViewport();
    await expect(item.block.root).not.toHaveClass(/\bflash\b/);
  });
});

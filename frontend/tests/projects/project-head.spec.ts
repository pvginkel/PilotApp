/**
 * A project's head (F2): the name, the ticket and the repo, linked; the step button and the plan
 * popover (F2.2, F3); the handbook's button (F129.4; its overlay in
 * timeline/project-documents.spec.ts); the plan's notes and a step's (F2.7, F3.6); the members (F2.5); the auto
 * pilot switch, the Finished chip in its place (F2.6, F4.1); a draft's and an archived project's
 * head (D012); a tight head giving way beside the side panel, its menu clear of it; everything it
 * opens closed on another project (F1.6); two rows on a narrow window.
 */

import type { Locator } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

type Status = 'pending' | 'in_progress' | 'done';
type Note = { id: string; summary: string; content: string };

const note = (id: string): Note => ({ id, summary: `Summary ${id}`, content: `Content ${id}` });
const step = (id: string, status: Status, notes: Note[] = []) => ({ id, title: `Step ${id}`, status, notes });

test.describe('The head', () => {
  test('links the name, the ticket and the repo as links that open a new tab, in the colour of the text around them', async ({
    page,
    backendUrl,
    people,
    projects,
    projectHead,
    links,
  }) => {
    await links.set({ ticket_url_template: `${backendUrl}/tickets/{id}` });
    const me = await people.signIn();
    const name = `${makeUnique('Port')} to pvginkel/Example`;
    const id = await projects.make({ name, ticket: 'PL-7', repo: 'pvginkel/Example', members: [me.handle!] });
    await projectHead.open(id);

    await expect(projectHead.name).toHaveText(name);
    await expect(projectHead.ticket).toHaveText('PL-7');
    await expect(projectHead.repo).toHaveText('pvginkel/Example');
    const ticket = projectHead.ticket.getByRole('link', { name: 'PL-7' });
    await expect(ticket).toHaveAttribute('href', `${backendUrl}/tickets/PL-7`);
    await expect(ticket).toHaveAttribute('target', '_blank');
    for (const repo of [projectHead.repo.getByRole('link'), projectHead.name.getByRole('link', { name: 'pvginkel/Example' })]) {
      await expect(repo).toHaveAttribute('href', 'https://github.com/pvginkel/Example');
      await expect(repo).toHaveAttribute('target', '_blank');
    }

    const style = (property: string) => ticket.evaluate((element, name) => getComputedStyle(element).getPropertyValue(name), property);
    expect(await style('color')).toBe(await projectHead.ticket.evaluate((element) => getComputedStyle(element).color));
    expect(await style('text-decoration-line')).toBe('none');
    await ticket.hover();
    await expect.poll(() => style('text-decoration-line')).toBe('underline');

    // A click opens the ticket in a new tab, the project staying on screen.
    const opened = page.waitForEvent('popup');
    await ticket.click();
    expect((await opened).url()).toBe(`${backendUrl}/tickets/PL-7`);
    await expect(page).toHaveURL(`/projects/${id}`);
  });

  test('reads the record again when the window comes back into focus', async ({ page, people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Focus'), members: [me.handle!] });
    await projectHead.open(id);
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');

    await projects.transition(id, 'autopilot_on');
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange', { bubbles: true })));
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
  });
});

test.describe('The step button', () => {
  test('reads the first step in progress, “, …” when more are, else “Not started”, “N of M done” or “All steps done”', async ({
    people,
    projects,
    projectHead,
  }) => {
    const me = await people.signIn();
    const cases: [ReturnType<typeof step>[], string][] = [
      [[step('a', 'pending'), step('b', 'pending')], 'Not started'],
      [[], 'Not started'],
      [[step('a', 'done'), step('b', 'pending'), step('c', 'pending')], '1 of 3 done'],
      [[step('a', 'done'), step('b', 'in_progress'), step('c', 'pending')], 'Step b'],
      [[step('a', 'in_progress'), step('b', 'pending'), step('c', 'in_progress')], 'Step a, …'],
      [[step('a', 'done'), step('b', 'done')], 'All steps done'],
    ];
    const ids: string[] = [];
    for (const [tasks] of cases) ids.push(await projects.make({ name: makeUnique('Plan'), members: [me.handle!], tasks }));

    for (const [index, [, reading]] of cases.entries()) {
      await projectHead.open(ids[index]);
      await expect(projectHead.step).toHaveText(reading);
    }
  });

  test('draws the plan’s donut, steps done, then in progress, then the rest, and lists every step in progress on hover', async ({
    people,
    projects,
    projectHead,
  }) => {
    const me = await people.signIn();
    const going = await projects.make({
      name: makeUnique('Going'),
      members: [me.handle!],
      tasks: [step('a', 'done'), step('b', 'in_progress'), step('c', 'pending'), step('d', 'in_progress')],
    });
    const waiting = await projects.make({ name: makeUnique('Waiting'), members: [me.handle!], tasks: [step('a', 'pending')] });
    const parts = () => projectHead.ring.locator('circle').evaluateAll((circles) => circles.map((circle) => circle.getAttribute('class')));

    await projectHead.open(going);
    await expect.poll(parts).toEqual(['done', 'now', 'rest']);
    await expect(projectHead.step).toHaveAttribute('title', '1 of 4 steps done · in progress: Step b; Step d');

    await projectHead.open(waiting);
    await expect.poll(parts).toEqual(['rest']);
    await expect(projectHead.step).toHaveAttribute('title', '0 of 1 steps done');
  });
});

test.describe('The plan popover', () => {
  test('lists the steps in order, done ones ticked, every step in progress highlighted', async ({ people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.make({
      name: makeUnique('Plan'),
      members: [me.handle!],
      tasks: [step('a', 'done'), step('b', 'in_progress'), step('c', 'pending'), step('d', 'in_progress')],
    });
    await projectHead.open(id);

    await expect(projectHead.plan).toHaveCount(0);
    await projectHead.step.click();
    await expect(projectHead.planHeading).toHaveText('The plan · 1 of 4 done');
    await expect(projectHead.planSteps).toHaveText(['Step a', 'Step b', 'Step c', 'Step d']);
    expect(await projectHead.planSteps.evaluateAll((steps) => steps.map((element) => element.dataset.state))).toEqual(['done', 'now', 'pending', 'now']);
    await expect(projectHead.planStep('Step b').root.locator('.mark')).toHaveAccessibleName('In progress');
    await expect(projectHead.planStep('Step a').root.locator('.mark svg')).toHaveCount(1);
    await expect(projectHead.planSteps.locator('.mark svg')).toHaveCount(1);

    const background = (title: string) => projectHead.planStep(title).root.evaluate((element) => getComputedStyle(element).backgroundColor);
    const highlighted = await background('Step b');
    expect(highlighted).not.toBe(await background('Step c'));
    expect(await background('Step d')).toBe(highlighted);
    expect(await background('Step a')).toBe(await background('Step c'));
  });

  test('a step’s title links: a span in the step button, a link in the popover', async ({
    page,
    backendUrl,
    people,
    projects,
    projectHead,
    links,
  }) => {
    await links.set({ ticket_url_template: `${backendUrl}/tickets/{id}` });
    const me = await people.signIn();
    const title = 'Port PL-7 to pvginkel/Example';
    const id = await projects.make({ name: makeUnique('Linked'), members: [me.handle!], tasks: [{ id: 'a', title, status: 'in_progress' }] });
    await projectHead.open(id);

    await expect(projectHead.step.getByRole('link', { name: 'pvginkel/Example' })).toHaveAttribute(
      'data-href',
      'https://github.com/pvginkel/Example',
    );
    const inButton = projectHead.step.getByRole('link', { name: 'PL-7' });
    await expect(inButton).toHaveAttribute('data-href', `${backendUrl}/tickets/PL-7`);
    await expect(inButton).not.toHaveAttribute('href');
    // The span opens the ticket, and not the plan.
    const opened = page.waitForEvent('popup');
    await inButton.click();
    const popup = await opened;
    expect(popup.url()).toBe(`${backendUrl}/tickets/PL-7`);
    await popup.close();
    await expect(projectHead.plan).toHaveCount(0);

    // Clicked beside the span, on the donut, the button opens the plan.
    await projectHead.ring.click();
    await expect(projectHead.plan.getByRole('link', { name: 'pvginkel/Example' })).toHaveAttribute('href', 'https://github.com/pvginkel/Example');
  });

  test('closes on a click outside it, on Esc and on its button', async ({ page, people, projects, projectHead, shell }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Closing'), members: [me.handle!], tasks: [step('a', 'in_progress')] });
    await projectHead.open(id);

    await projectHead.step.click();
    await expect(projectHead.plan).toBeVisible();
    // A click inside it leaves it open.
    await projectHead.planHeading.click();
    await expect(projectHead.plan).toBeVisible();
    await shell.centre.click({ position: { x: 300, y: 400 } });
    await expect(projectHead.plan).toHaveCount(0);

    await projectHead.step.click();
    await expect(projectHead.plan).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(projectHead.plan).toHaveCount(0);

    await projectHead.step.click();
    await expect(projectHead.plan).toBeVisible();
    await projectHead.step.click();
    await expect(projectHead.plan).toHaveCount(0);
  });

  test('beside a step with open notes, the sticky-note icon lists them on hover, never a count', async ({ people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.make({
      name: makeUnique('Notes'),
      members: [me.handle!],
      tasks: [step('a', 'in_progress', [note('first'), note('second')]), step('b', 'pending')],
      notes: [note('plan')],
    });
    await projectHead.open(id);
    await projectHead.step.click();

    const noted = projectHead.planStep('Step a');
    await expect(noted.notesButton).toHaveText('');
    await expect(projectHead.planStep('Step b').notesButton).toHaveCount(0);
    await expect(noted.notes).toHaveCount(0);

    await noted.notesButton.hover();
    await expect(noted.notes.getByTestId('project.plan.step.notes.note.summary')).toHaveText(['Summary first', 'Summary second']);
    await expect(noted.notes.getByTestId('project.plan.step.notes.note.content')).toHaveText(['Content first', 'Content second']);
    await projectHead.planHeading.hover();
    await expect(noted.notes).toHaveCount(0);
    // The plan's own notes are the head's, not the popover's.
    await expect(projectHead.plan).not.toContainText('Summary plan');
  });

  test('scrolls inside the window', async ({ page, people, projects, projectHead }) => {
    const me = await people.signIn();
    const tasks = Array.from({ length: 40 }, (_, index) => step(`s${index}`, 'pending'));
    const id = await projects.make({ name: makeUnique('Long'), members: [me.handle!], tasks });
    await projectHead.open(id);
    await projectHead.step.click();

    const box = (await projectHead.plan.boundingBox())!;
    expect(box.y + box.height).toBeLessThanOrEqual(page.viewportSize()!.height);
    expect(await projectHead.plan.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
    await projectHead.planStep('Step s39').root.scrollIntoViewIfNeeded();
    await expect(projectHead.planStep('Step s39').root).toBeInViewport();
  });
});

test.describe('The plan’s notes', () => {
  test('a button in the head while the plan has open notes, opening them, summary and content, nothing editable', async ({
    page,
    people,
    projects,
    projectHead,
  }) => {
    const me = await people.signIn();
    const noted = await projects.make({ name: makeUnique('Noted'), members: [me.handle!], notes: [note('one'), note('two')] });
    const bare = await projects.make({
      name: makeUnique('Bare'),
      members: [me.handle!],
      tasks: [step('a', 'in_progress', [note('step')])],
    });

    await projectHead.open(bare);
    await expect(projectHead.step).toBeVisible();
    await expect(projectHead.notesButton).toHaveCount(0);

    await projectHead.open(noted);
    await expect(projectHead.notesButton).toHaveText('');
    await projectHead.notesButton.click();
    await expect(projectHead.notes.getByTestId('project.notes.list.note.summary')).toHaveText(['Summary one', 'Summary two']);
    await expect(projectHead.notes.getByTestId('project.notes.list.note.content')).toHaveText(['Content one', 'Content two']);
    await expect(projectHead.notes.locator('input, textarea, select, button, [contenteditable]')).toHaveCount(0);

    await page.keyboard.press('Escape');
    await expect(projectHead.notes).toHaveCount(0);
    await projectHead.notesButton.click();
    await expect(projectHead.notes).toBeVisible();
    await projectHead.name.click();
    await expect(projectHead.notes).toHaveCount(0);
  });
});

test.describe('The members', () => {
  test('show as avatars in the order they joined, overlapping by 2px', async ({ people, projects, projectHead }) => {
    const me = await people.signIn({ name: 'Test Person' });
    const id = await projects.make({ name: makeUnique('Members'), members: ['ben', me.handle!, 'ada'] });
    await projectHead.open(id);

    const avatars = projectHead.members.locator('.avatar');
    await expect(avatars).toHaveText(['BE', 'TP', 'AE']);
    expect(await avatars.evaluateAll((elements) => elements.map((element) => element.getAttribute('title')))).toEqual([
      'Ben Example',
      'Test Person',
      'Ada Example',
    ]);
    expect(await avatars.evaluateAll((elements) => elements.map((element) => element.getAttribute('data-colour')))).toEqual([
      '2',
      String(((me.avatar_slot! - 1) % 6) + 1),
      '1',
    ]);
    const [first, second] = [(await avatars.nth(0).boundingBox())!, (await avatars.nth(1).boundingBox())!];
    expect(second.x).toBeCloseTo(first.x + first.width - 2, 1);
  });
});

test.describe('Auto pilot', () => {
  test('the switch flips auto pilot on the record, each way', async ({ people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Switch'), members: [me.handle!] });
    await projectHead.open(id);

    await expect(projectHead.autopilot).toHaveText('Auto pilot');
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
    await projectHead.autopilot.click();
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
    expect((await projects.head(id)).autopilot).toBe(true);

    await projectHead.autopilot.click();
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
    expect((await projects.head(id)).autopilot).toBe(false);
  });

  test('a finished project shows the Finished chip in the switch’s place', async ({ people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Done'), state: 'finished', members: [me.handle!], tasks: [step('a', 'done')] });
    await projectHead.open(id);

    await expect(projectHead.finished).toHaveText('Finished');
    await expect(projectHead.autopilot).toHaveCount(0);
    await expect(projectHead.step).toHaveText('All steps done');
  });
});

test.describe('A draft’s head', () => {
  test('has its name, the Draft chip and its members, and no switch, step or Documents button, nor a side panel on a wide window', async ({
    people,
    projects,
    projectHead,
    panel,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Draft');
    const named = await projects.make({ name, state: 'draft', members: [me.handle!] });
    const untitled = await projects.make({ state: 'draft', members: [me.handle!] });

    await projectHead.open(named);
    await expect(projectHead.name).toHaveText(name);
    await expect(projectHead.draft).toHaveText('Draft');
    await expect(projectHead.members.locator('.avatar')).toHaveCount(1);
    await expect(projectHead.autopilot).toHaveCount(0);
    await expect(projectHead.step).toHaveCount(0);
    await expect(projectHead.documentsButton).toHaveCount(0);
    await expect(panel.root).toHaveCount(0);

    await projectHead.open(untitled);
    await expect(projectHead.name).toHaveText('New project');
  });
});

test.describe('An archived project’s head', () => {
  test('reads as it was left, marked archived, its switch not to be flipped', async ({ people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.make({
      name: makeUnique('Archived'),
      archived: true,
      autopilot: true,
      members: [me.handle!],
      tasks: [step('a', 'done'), step('b', 'in_progress')],
      notes: [note('kept')],
    });
    await projectHead.open(id);

    await expect(projectHead.archived).toHaveText('Archived');
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
    await expect(projectHead.autopilot).toBeDisabled();
    await expect(projectHead.step).toHaveText('Step b');
    await expect(projectHead.notesButton).toBeVisible();
  });
});

test.describe('A tight head beside the side panel', () => {
  const LONG_STEP = { id: 'a', title: 'A step whose title runs on well past what the head has room for', status: 'in_progress' as const, notes: [] };
  const cut = (locator: Locator) => locator.evaluate((element) => element.scrollWidth > element.clientWidth);

  test('gives way in the repo and the step’s name first, the name whole', async ({ people, projects, projectHead, panel }) => {
    const me = await people.signIn();
    const id = await projects.make({
      name: makeUnique('Tight'),
      ticket: 'PL-7',
      repo: 'pvginkel/a-repository-whose-name-runs-on-and-on',
      members: [me.handle!],
      tasks: [LONG_STEP],
    });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();

    expect(await cut(projectHead.step.getByTestId('project.step.name'))).toBe(true);
    expect(await cut(projectHead.repo)).toBe(true);
    expect(await cut(projectHead.name)).toBe(false);
  });

  test('gives way in the name once they have, the chips, the members and the icons whole, the menu inside the head and clear of the panel', async ({
    people,
    projects,
    projectHead,
    panel,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({
      name: `${makeUnique('Tight')} has a name long enough to fill a project’s head on its own`,
      state: 'finished',
      archived: true,
      ticket: 'PL-7',
      repo: 'pvginkel/Example',
      members: [me.handle!, 'ada'],
      tasks: [LONG_STEP],
      notes: [note('one')],
    });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();

    expect(await cut(projectHead.name)).toBe(true);
    for (const whole of [projectHead.archived, projectHead.finished, projectHead.members]) expect(await cut(whole)).toBe(false);
    expect(await projectHead.root.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    const [head, menu, aside] = await Promise.all(
      [projectHead.root, projectHead.menuButton, panel.root].map(async (locator) => (await locator.boundingBox())!),
    );
    expect(menu.x + menu.width).toBeLessThanOrEqual(head.x + head.width);
    expect(head.x + head.width).toBeLessThanOrEqual(aside.x);
    await projectHead.menuButton.click();
    await expect(projectHead.menuItems).toHaveText(['Bring back']);
  });
});

test.describe('Switching projects', () => {
  test('closes the plan and the plan’s notes', async ({ page, people, projects, projectHead, projectList }) => {
    const me = await people.signIn();
    const spec = { members: [me.handle!], tasks: [step('a', 'in_progress')], notes: [note('one')] };
    const a = await projects.make({ name: makeUnique('A'), ...spec });
    const b = makeUnique('B');
    const bId = await projects.make({ name: b, ...spec });
    await projectHead.open(a);
    await projectList.tab(b).click();
    await expect(page).toHaveURL(`/projects/${bId}`);

    // Back and Forward press nothing on the page: only another project closes what is open.
    await projectHead.step.click();
    await expect(projectHead.plan).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(`/projects/${a}`);
    await expect(projectHead.step).toBeVisible();
    await expect(projectHead.plan).toHaveCount(0);

    await projectHead.notesButton.click();
    await expect(projectHead.notes).toBeVisible();
    await page.goForward();
    await expect(page).toHaveURL(`/projects/${bId}`);
    await expect(projectHead.step).toBeVisible();
    await expect(projectHead.notes).toHaveCount(0);
    await expect(projectHead.plan).toHaveCount(0);
  });
});

test.describe('The head on a narrow window', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('keeps two rows, the name and auto pilot, then the step, the members and the icons, the repo hidden', async ({
    people,
    projects,
    projectHead,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({
      name: makeUnique('Phone'),
      ticket: 'PL-7',
      repo: 'pvginkel/Example',
      members: [me.handle!, 'ada'],
      tasks: [step('a', 'in_progress')],
      notes: [note('one')],
    });
    await projectHead.open(id);

    await expect(projectHead.ticket).toBeVisible();
    await expect(projectHead.repo).toBeHidden();
    const [name, autopilot, stepButton, members, handbook, notes] = await Promise.all(
      [projectHead.name, projectHead.autopilot, projectHead.step, projectHead.members, projectHead.handbookButton, projectHead.notesButton].map(
        async (locator) => (await locator.boundingBox())!,
      ),
    );
    const middle = (box: { y: number; height: number }) => box.y + box.height / 2;
    expect(middle(autopilot)).toBeCloseTo(middle(name), -1);
    expect(stepButton.y).toBeGreaterThanOrEqual(autopilot.y + autopilot.height);
    expect(middle(members)).toBeCloseTo(middle(stepButton), -1);
    expect(middle(handbook)).toBeCloseTo(middle(stepButton), -1);
    expect(handbook.x).toBeGreaterThan(members.x + members.width);
    expect(middle(notes)).toBeCloseTo(middle(stepButton), -1);
    expect(notes.x + notes.width).toBeLessThanOrEqual(390);
  });

  test('a tap on a step’s sticky-note icon lists its notes, the plan within the window', async ({ people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.make({
      name: makeUnique('Tap'),
      members: [me.handle!],
      tasks: [step('a', 'in_progress', [note('tapped')])],
    });
    await projectHead.open(id);

    await projectHead.step.tap();
    const box = (await projectHead.plan.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(390);

    const noted = projectHead.planStep('Step a');
    await noted.notesButton.tap();
    await expect(noted.notes.getByTestId('project.plan.step.notes.note.summary')).toHaveText(['Summary tapped']);
    await noted.notesButton.tap();
    await expect(noted.notes).toHaveCount(0);
    await expect(projectHead.plan).toBeVisible();
  });
});

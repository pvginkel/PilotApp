/**
 * A project's head (F2): the name, the ticket and the repo, linked; its controls, with no Discuss,
 * Documents or handbook button (F2.3); the step button and the plan popover (F2.2, F3); the plan's
 * notes and a step's (F2.7, F3.6); the members (F2.5); the auto pilot switch, the Finished chip in
 * its place (F2.6, F4.1); a draft's head, its menu its one control (F46.2; its panel in
 * draft-panel.spec.ts), and an archived project's head (D012); a tight head
 * beside the side panel giving way in one order, the repo, the name, the step's name to its floor,
 * then the members folding to a count, then standing in two rows, its menu clear of the panel,
 * a tab open or not;
 * everything it opens closed on another project (F1.6); on a phone one line (F2.8): the switch
 * without its label, the donut alone showing the Plan tab (F3.7), the members two circles at most,
 * the name giving way, a draft's, a finished and an archived project's, their chips their icon alone.
 */

import type { Locator, Page } from '@playwright/test';
import type { FormTestEvent } from '@/lib/test/test-events';
import type { People } from '../support/people';
import type { ProjectHeadPage } from '../support/page-objects/project-head-page';
import type { TimelinePage } from '../support/page-objects/timeline-page';
import { lift } from '../support/chips';
import { test, expect } from '../support/fixtures';
import { makeUnique, waitTestEvent } from '../support/helpers';
import { PageFetches } from '../support/network';
import { projectAddress, type Projects } from '../support/projects';

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
    await expect(page).toHaveURL(projectAddress(id));
  });

  test('has no Discuss, Documents or handbook button: its controls are the switch, the step button, the plan’s notes and the menu, the icons after the members', async ({
    people,
    projects,
    projectHead,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Controls'), members: [me.handle!], tasks: [step('a', 'in_progress')], notes: [note('one')] });
    await projectHead.open(id);

    expect(await projectHead.controls()).toEqual(['project.autopilot', 'project.step', 'project.notes.button', 'project.menu.button']);
    const [members, notes, menu] = await Promise.all(
      [projectHead.members, projectHead.notesButton, projectHead.menuButton].map(async (locator) => (await locator.boundingBox())!),
    );
    expect(notes.x).toBeGreaterThan(members.x + members.width);
    // Icon buttons side by side touch.
    expect(menu.x).toBeCloseTo(notes.x + notes.width, 0);
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
    expect(await projectHead.planHeading.evaluate((heading) => getComputedStyle(heading).fontWeight)).toBe('600');
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

  test('a step’s title links: a span in the step button, its ticket id plain text there, and a link in the popover', async ({
    page,
    backendUrl,
    people,
    projects,
    projectHead,
    links,
  }) => {
    await links.set({ ticket_url_template: `${backendUrl}/tickets/{id}`, environment_link_base_url: `${backendUrl}/kubecoder` });
    const lab = { id: makeUnique('env'), name: `${makeUnique('Lab')}-1` };
    await links.environment(lab.id, lab.name);
    const me = await people.signIn();
    const title = `Port PL-7 to pvginkel/Example on ${lab.name}`;
    const id = await projects.make({ name: makeUnique('Linked'), members: [me.handle!], tasks: [{ id: 'a', title, status: 'in_progress' }] });
    await projectHead.open(id);

    await expect(projectHead.step).toHaveText(title);
    await expect(projectHead.step.getByRole('link', { name: 'pvginkel/Example' })).toHaveAttribute(
      'data-href',
      'https://github.com/pvginkel/Example',
    );
    // A tap meant for the button never opens the tracker.
    await expect(projectHead.step.getByRole('link', { name: 'PL-7' })).toHaveCount(0);
    const inButton = projectHead.step.getByRole('link', { name: lab.name });
    const opens = `${backendUrl}/kubecoder/environments/${lab.id}/ssh/open`;
    await expect(inButton).toHaveAttribute('data-href', opens);
    await expect(inButton).not.toHaveAttribute('href');
    // The span opens the environment, and not the plan.
    const opened = page.waitForEvent('popup');
    await inButton.click();
    const popup = await opened;
    expect(popup.url()).toBe(opens);
    await popup.close();
    await expect(projectHead.plan).toHaveCount(0);

    // Clicked beside the span, on the donut, the button opens the plan, whose step links all three.
    await projectHead.ring.click();
    await expect(projectHead.plan.getByRole('link', { name: 'pvginkel/Example' })).toHaveAttribute('href', 'https://github.com/pvginkel/Example');
    await expect(projectHead.plan.getByRole('link', { name: 'PL-7' })).toHaveAttribute('href', `${backendUrl}/tickets/PL-7`);
    await expect(projectHead.plan.getByRole('link', { name: lab.name })).toHaveAttribute('href', opens);
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

/** The Draft chip's words against a "for" chip's, a chip of the shared style, on an item of another project. */
async function draftChipAgainstShared(
  people: People,
  projects: Projects,
  projectHead: ProjectHeadPage,
  timeline: TimelinePage,
): Promise<void> {
  const me = await people.signIn();
  const id = await projects.makeWithSession({ name: makeUnique('Chips'), members: [me.handle!, 'ada'] });
  const notice = await projects.place(id, { kind: 'notice', title: 'For Ada', text: '---\nfor: ada\n---\n\nA note for Ada.\n' });
  const draft = await projects.make({ name: makeUnique('Draft'), state: 'draft', members: [me.handle!] });
  await timeline.open(id);
  const shared = await lift(timeline.item(notice).forUser);

  await projectHead.open(draft);
  const own = await lift(projectHead.draft);
  expect(own.lift - shared.lift).toBeCloseTo(1, 1);
  expect(own.height).toBeCloseTo(shared.height, 1);
}

/** The switch's flip answered, by the server's yes or its refusal: each in turn, as they come. */
const flipAnswered = (page: Page) =>
  waitTestEvent<FormTestEvent>(page, 'form', (event) => event.formId === 'project.autopilot' && event.phase !== 'submit');

/** Flips the switch through the page once it is answered, and gives the page's sender, which every write of the page names. */
async function flipThrough(page: Page, projectHead: ProjectHeadPage, id: string): Promise<string> {
  const flipped = page.waitForRequest((request) => request.method() === 'POST' && request.url().endsWith(`/api/projects/${id}/transitions`));
  await projectHead.autopilot.click();
  await flipAnswered(page);
  return (await flipped).headers()['x-sender'];
}

/**
 * A transition behind the page's back: naming the page as its sender, it is one the page takes for
 * its own write, which reads nothing on its event.
 */
async function behind(page: Page, backendUrl: string, id: string, kind: string, sender: string): Promise<void> {
  const response = await page.request.post(`${backendUrl}/api/projects/${id}/transitions`, { data: { kind }, headers: { 'X-Sender': sender } });
  expect(response.status(), await response.text()).toBe(201);
}

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

  test('a fast double tap turns it on, the second tap’s refusal read against the project and toasting nothing', async ({
    page,
    people,
    projects,
    projectHead,
    appShell,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Double'), members: [me.handle!] });
    await projectHead.open(id);
    const flips: string[] = [];
    page.on('request', (request) => {
      if (request.method() === 'POST' && request.url().endsWith(`/api/projects/${id}/transitions`)) flips.push(request.postDataJSON().kind);
    });
    const fetches = new PageFetches(page);

    await projectHead.autopilot.dblclick();
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
    await fetches.landed();
    expect(flips).toEqual(['autopilot_on', 'autopilot_on']);
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
    await expect(appShell.toastItems).toHaveCount(0);
    expect((await projects.head(id)).autopilot).toBe(true);
  });

  test('a page left stale behind its back reads the project again on the refusal, and where it stands as asked toasts nothing', async ({
    page,
    backendUrl,
    people,
    projects,
    projectHead,
    appShell,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Stale'), members: [me.handle!] });
    await projectHead.open(id);
    const sender = await flipThrough(page, projectHead, id);
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');

    for (const [kind, shown] of [
      ['autopilot_off', 'false'],
      ['autopilot_on', 'true'],
    ] as const) {
      await behind(page, backendUrl, id, kind, sender);
      await expect(projectHead.autopilot).not.toHaveAttribute('aria-checked', shown);
      await projectHead.autopilot.click();
      expect((await flipAnswered(page)).phase).toBe('success');
      await expect(projectHead.autopilot).toHaveAttribute('aria-checked', shown);
      await expect(appShell.toastItems).toHaveCount(0);
    }
  });

  test('a refusal after which the project does not stand as asked toasts the server’s words once, the head read again', async ({
    page,
    backendUrl,
    people,
    projects,
    projectHead,
    appShell,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Refused');
    const id = await projects.make({ name, members: [me.handle!] });
    await projectHead.open(id);
    const sender = await flipThrough(page, projectHead, id);
    await projectHead.autopilot.click();
    await flipAnswered(page);
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
    await behind(page, backendUrl, id, 'finished', sender);
    await expect(projectHead.autopilot).toBeVisible();

    await projectHead.autopilot.click();
    expect((await flipAnswered(page)).phase).toBe('error');
    await expect(projectHead.finished).toBeVisible();
    await expect(appShell.toastItems).toHaveCount(1);
    await expect(appShell.toastItems).toContainText(`Cannot turn auto pilot on for ${name} because it is finished`);
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
  test('has its name, the Draft chip, its members and its menu, its one control: no switch, step or toggle; its side panel stands on the Draft tab on a wide window', async ({
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
    expect(await projectHead.controls()).toEqual(['project.menu.button']);
    await expect(panel.draftTab).toHaveAttribute('aria-selected', 'true');

    await projectHead.open(untitled);
    await expect(projectHead.name).toHaveText('New project');
  });

  test('its Draft chip’s word stands a pixel higher in its pill than a shared chip’s, the pill as high', async ({ people, projects, projectHead, timeline }) => {
    await draftChipAgainstShared(people, projects, projectHead, timeline);
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
  // The step's name gives way down to this width (steps-button.tsx).
  const NAME_FLOOR = 28;
  // The project's name gives way in one row down to this width, where it is wider (project-head.tsx).
  const PROJECT_NAME_FLOOR = 250;
  const cut = (locator: Locator) => locator.evaluate((element) => element.scrollWidth > element.clientWidth);
  const width = async (locator: Locator) => (await locator.boundingBox())!.width;

  /** Six people on the record, the spec's own person first: the members in the order they join. */
  async function six(people: { other(handle: string, name?: string): Promise<void> }, me: string): Promise<{ handles: string[]; names: string[] }> {
    const others = [1, 2, 3, 4].map((n) => ({ handle: makeUnique(`m${n}`, 6), name: `Member ${n}` }));
    for (const other of others) await people.other(other.handle, other.name);
    return {
      handles: [me, 'ada', ...others.map((other) => other.handle)],
      names: ['Test Person', 'Ada Example', ...others.map((other) => other.name)],
    };
  }

  /**
   * Every part of the head that shows, left to right in its row, each clear of the next and inside
   * the head; in one row the step's anchor is its button's width, no blank standing beside it; in
   * either the step's button no wider than 350 px.
   */
  async function clear(projectHead: ProjectHeadPage, panel: { root: Locator }): Promise<void> {
    const parts = await projectHead.root.evaluate((head) =>
      Array.from(head.querySelectorAll(':scope > .head-row > *, .members > *, .step-anchor > .btn'))
        .filter((part) => !part.classList.contains('step-anchor') && !part.classList.contains('members') && !part.classList.contains('grow'))
        .map((part) => part.getBoundingClientRect())
        .filter((box) => box.width > 0)
        .map((box) => ({ left: box.left, right: box.right, top: box.top, bottom: box.bottom })),
    );
    const head = (await projectHead.root.boundingBox())!;
    for (const [index, part] of parts.slice(1).entries()) {
      // A part below the one before it starts the second row.
      if (part.top >= parts[index].bottom) continue;
      // The avatars overlap by 2px on purpose.
      expect(part.left).toBeGreaterThanOrEqual(parts[index].right - 2.01);
    }
    for (const part of parts) expect(part.right).toBeLessThanOrEqual(head.x + head.width);
    expect(head.x + head.width).toBeLessThanOrEqual((await panel.root.boundingBox())!.x);
    const blank = await projectHead.root.evaluate((element) => {
      const anchor = element.querySelector('.step-anchor');
      if (element.classList.contains('two-rows') || anchor === null) return 0;
      return anchor.getBoundingClientRect().width - anchor.querySelector('.btn')!.getBoundingClientRect().width;
    });
    expect(blank).toBeCloseTo(0, 1);
    // The step's button keeps its 350 px cap (D172) in either row, its anchor filling the second.
    const step = await projectHead.root.evaluate((element) => element.querySelector('.step-anchor > .btn')?.getBoundingClientRect().width ?? 0);
    expect(step).toBeLessThanOrEqual(350.01);
  }

  /** Whether the head stands in its two rows: the step below the name's row. */
  async function twoRows(projectHead: ProjectHeadPage): Promise<boolean> {
    const [name, stepButton] = await Promise.all([projectHead.name, projectHead.step].map(async (locator) => (await locator.boundingBox())!));
    return stepButton.y >= name.y + name.height;
  }

  /** Letter-spacing stands in for a wider font, as Jenkins' is. */
  async function widen(page: Page): Promise<void> {
    await page.addInitScript(() =>
      document.addEventListener('DOMContentLoaded', () => {
        const style = document.createElement('style');
        style.textContent = 'body { letter-spacing: 0.12em; }';
        document.head.append(style);
      }),
    );
  }

  test('gives way in the repo first, then the name above its floor, the ticket and the step’s name whole', async ({ page, people, projects, projectHead, panel }) => {
    await page.setViewportSize({ width: 1500, height: 720 });
    const me = await people.signIn();
    const id = await projects.make({
      name: `${makeUnique('Tight')} has a long name that runs on past its row`,
      ticket: 'PL-7',
      repo: 'pvginkel/a-repository-whose-name-runs-on-and-on',
      members: [me.handle!, 'ada'],
      tasks: [{ id: 'a', title: 'Import', status: 'in_progress', notes: [] }],
    });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();

    expect(await twoRows(projectHead)).toBe(false);
    expect(await width(projectHead.repo)).toBe(0);
    expect(await cut(projectHead.name)).toBe(true);
    expect(await width(projectHead.name)).toBeGreaterThan(PROJECT_NAME_FLOOR + 1);
    expect(await cut(projectHead.ticket)).toBe(false);
    expect(await cut(projectHead.step.getByTestId('project.step.name'))).toBe(false);
    await clear(projectHead, panel);
  });

  test('then the step’s name once the name is at its floor, 250px, the members whole while the step’s name is above its own', async ({
    page,
    people,
    projects,
    projectHead,
    panel,
  }) => {
    await page.setViewportSize({ width: 1440, height: 720 });
    const me = await people.signIn();
    const id = await projects.make({
      name: `${makeUnique('Tight')} has a long name that runs on`,
      ticket: 'PL-7',
      members: [me.handle!, 'ada', 'ben'],
      tasks: [LONG_STEP],
    });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();

    expect(await twoRows(projectHead)).toBe(false);
    expect(await cut(projectHead.name)).toBe(true);
    expect(await width(projectHead.name)).toBeCloseTo(PROJECT_NAME_FLOOR, 1);
    const name = projectHead.step.getByTestId('project.step.name');
    expect(await cut(name)).toBe(true);
    expect(await width(name)).toBeGreaterThan(NAME_FLOOR);
    await expect(projectHead.memberAvatars).toHaveCount(3);
    await expect(projectHead.membersMore).toHaveCount(0);
    await clear(projectHead, panel);
  });

  test('a name narrower than the floor gives way not at all, the step’s name giving way beside it', async ({ page, people, projects, projectHead, panel }) => {
    await page.setViewportSize({ width: 1340, height: 720 });
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Short'), ticket: 'PL-7', members: [me.handle!, 'ada'], tasks: [LONG_STEP] });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();

    expect(await twoRows(projectHead)).toBe(false);
    expect(await width(projectHead.name)).toBeLessThan(PROJECT_NAME_FLOOR);
    expect(await cut(projectHead.name)).toBe(false);
    expect(await cut(projectHead.step.getByTestId('project.step.name'))).toBe(true);
    await clear(projectHead, panel);
  });

  test('the step button stands no wider than 350px, its name cut and its tooltip naming the steps in progress whole', async ({
    page,
    people,
    projects,
    projectHead,
    panel,
  }) => {
    await page.setViewportSize({ width: 1800, height: 720 });
    const me = await people.signIn();
    const other = { id: 'b', title: 'Another step in progress whose title is long as well', status: 'in_progress' as const, notes: [] };
    const id = await projects.make({ name: makeUnique('Cap'), members: [me.handle!], tasks: [LONG_STEP, other, step('c', 'done')] });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();

    expect(await width(projectHead.step)).toBeCloseTo(350, 1);
    expect(await cut(projectHead.step.getByTestId('project.step.name'))).toBe(true);
    await expect(projectHead.step.getByTestId('project.step.name')).toHaveText(LONG_STEP.title);
    await expect(projectHead.step).toHaveAttribute('title', `1 of 3 steps done · in progress: ${LONG_STEP.title}; ${other.title}`);
    expect(await cut(projectHead.name)).toBe(false);
    await clear(projectHead, panel);
  });

  test('the name gives way only for what the step button takes at its cap, above its floor beside a step at 350px', async ({
    page,
    people,
    projects,
    projectHead,
    panel,
  }) => {
    await page.setViewportSize({ width: 1700, height: 720 });
    const me = await people.signIn();
    const id = await projects.make({
      name: `${makeUnique('Tight')} has a long name that runs on`,
      ticket: 'PL-7',
      members: [me.handle!, 'ada', 'ben'],
      tasks: [LONG_STEP],
    });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();

    expect(await twoRows(projectHead)).toBe(false);
    expect(await width(projectHead.step)).toBeCloseTo(350, 1);
    expect(await cut(projectHead.name)).toBe(true);
    expect(await width(projectHead.name)).toBeGreaterThan(PROJECT_NAME_FLOOR + 1);
    await clear(projectHead, panel);
  });

  test('in its two rows the name has its row’s room, below its floor only where the row holds no more', async ({ page, people, projects, projectHead, panel }) => {
    await page.setViewportSize({ width: 1200, height: 720 });
    const me = await people.signIn();
    const id = await projects.make({
      name: `${makeUnique('Rows')} has a name long enough to fill a project’s head on its own`,
      archived: true,
      ticket: 'PILOT-1207',
      members: [me.handle!, 'ada'],
      tasks: [LONG_STEP],
    });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();

    expect(await twoRows(projectHead)).toBe(true);
    const [name, archived, autopilot] = await Promise.all([projectHead.name, projectHead.archived, projectHead.autopilot].map(async (locator) => (await locator.boundingBox())!));
    expect(name.width).toBeLessThan(PROJECT_NAME_FLOOR);
    // The name, the chip, the ticket and the switch fill the row.
    expect(autopilot.x + autopilot.width).toBeCloseTo((await projectHead.root.boundingBox())!.x + (await projectHead.root.boundingBox())!.width - 24, 0);
    expect(archived.x).toBeCloseTo(name.x + name.width + 12, 0);
    await clear(projectHead, panel);
  });

  test('gives way in the name once the repo has, the chips, the members and the icons whole, the menu inside the head and clear of the panel', async ({
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
    for (const whole of [projectHead.archived, projectHead.finished, projectHead.ticket, projectHead.members]) expect(await cut(whole)).toBe(false);
    expect(await projectHead.root.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await clear(projectHead, panel);
    await projectHead.menuButton.click();
    await expect(projectHead.menuItems).toHaveText(['Bring back']);
  });

  test('a click on the ticket’s last pixels opens the ticket and flips no auto pilot', async ({
    page,
    backendUrl,
    people,
    projects,
    projectHead,
    panel,
    links,
  }) => {
    // One row, the repo given way and the name cut above its floor.
    await page.setViewportSize({ width: 1500, height: 720 });
    await links.set({ ticket_url_template: `${backendUrl}/tickets/{id}` });
    const me = await people.signIn();
    const id = await projects.make({
      name: 'Port the recipe importer to the API',
      ticket: 'RB-12',
      repo: 'pvginkel/Recipes',
      members: [me.handle!, 'ada'],
      tasks: [{ id: 'a', title: 'Write the importer', status: 'in_progress', notes: [] }],
    });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();
    expect(await width(projectHead.repo)).toBe(0);

    const ticket = projectHead.ticket.getByRole('link', { name: 'RB-12' });
    const box = (await ticket.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual((await projectHead.autopilot.boundingBox())!.x);
    const opened = page.waitForEvent('popup');
    await ticket.click({ position: { x: box.width - 0.5, y: box.height / 2 } });
    expect((await opened).url()).toBe(`${backendUrl}/tickets/RB-12`);
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
    expect((await projects.head(id)).autopilot).toBe(false);
  });

  test('the step’s ring stays clear of the first member, and the ticket of the Finished chip', async ({ page, people, projects, projectHead, panel }) => {
    await page.setViewportSize({ width: 1200, height: 720 });
    const me = await people.signIn({ name: 'Test Person' });
    const { handles } = await six(people, me.handle!);
    const id = await projects.make({
      name: `${makeUnique('Ring')} has a long name`,
      state: 'finished',
      ticket: 'RB-12',
      members: handles,
      tasks: [LONG_STEP],
    });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();

    const [ring, avatar, ticket, finished] = await Promise.all(
      [projectHead.ring, projectHead.memberAvatars.first(), projectHead.ticket, projectHead.finished].map(async (locator) => (await locator.boundingBox())!),
    );
    expect(ring.x + ring.width).toBeLessThanOrEqual(avatar.x);
    expect(ticket.x + ticket.width).toBeLessThanOrEqual(finished.x);
    await clear(projectHead, panel);
  });

  for (const font of ['the default font', 'a wider font'] as const) {
    test(`at 1480px, in ${font}, the members fold last to the first avatars and a count naming the rest, the names at their floors and the menu inside the head`, async ({
      page,
      people,
      projects,
      projectHead,
      panel,
    }) => {
      await page.setViewportSize({ width: 1480, height: 720 });
      if (font === 'a wider font') await widen(page);
      const me = await people.signIn({ name: 'Test Person' });
      const { handles, names } = await six(people, me.handle!);
      const id = await projects.make({
        name: `${makeUnique('Six')} has a long name that runs on`,
        ticket: 'RB-1207',
        repo: 'pvginkel/Recipes',
        members: handles,
        tasks: [LONG_STEP],
        notes: [note('one')],
      });
      await projectHead.open(id);
      await expect(panel.root).toBeVisible();

      await expect(projectHead.membersMore).toBeVisible();
      const shown = await projectHead.memberAvatars.count();
      expect(shown).toBeGreaterThanOrEqual(1);
      expect(await projectHead.memberAvatars.evaluateAll((avatars) => avatars.map((avatar) => avatar.getAttribute('title')))).toEqual(names.slice(0, shown));
      await expect(projectHead.membersMore).toHaveText(`+${6 - shown}`);
      await expect(projectHead.membersMore).toHaveAttribute('title', names.slice(shown).join(', '));
      expect(await width(projectHead.step.getByTestId('project.step.name'))).toBeCloseTo(NAME_FLOOR, 0);
      expect(await width(projectHead.name)).toBeCloseTo(PROJECT_NAME_FLOOR, 1);
      expect(await twoRows(projectHead)).toBe(false);
      await clear(projectHead, panel);
    });
  }

  for (const font of ['the default font', 'a wider font'] as const) {
    test(`an archived head at 1490px, in ${font}, stands in its two rows once its parts at their floors run past it in one, and in one again once brought back`, async ({
      page,
      people,
      projects,
      projectHead,
      panel,
    }) => {
      await page.setViewportSize({ width: 1490, height: 720 });
      if (font === 'a wider font') await widen(page);
      const me = await people.signIn({ name: 'Test Person' });
      const { handles } = await six(people, me.handle!);
      const id = await projects.make({
        name: `${makeUnique('Archived')} has a long name`,
        archived: true,
        ticket: 'PILOT-1207',
        members: handles,
        tasks: [LONG_STEP],
        notes: [note('one')],
      });
      await projectHead.open(id);
      await expect(panel.root).toBeVisible();

      await clear(projectHead, panel);
      expect(await twoRows(projectHead)).toBe(true);

      await projectHead.choose('bring-back');
      await projectHead.confirm('bring-back');
      await expect(projectHead.archived).toHaveCount(0);
      expect(await twoRows(projectHead)).toBe(false);
      await clear(projectHead, panel);
    });
  }

  test('an archived head at 1200px with a tab open stands in its two rows over the tab line, as with none', async ({
    page,
    people,
    projects,
    projectHead,
    panel,
    docTabs,
  }) => {
    await page.setViewportSize({ width: 1200, height: 720 });
    const me = await people.signIn({ name: 'Test Person' });
    const { handles } = await six(people, me.handle!);
    const id = await projects.make({
      name: `${makeUnique('Archived')} has a long name`,
      archived: true,
      ticket: 'PILOT-1207',
      members: handles,
      tasks: [LONG_STEP],
      notes: [note('one')],
    });
    await projectHead.open(id);
    expect(await twoRows(projectHead)).toBe(true);

    await panel.documentsTab.click();
    await panel.handbook.root.click();
    await expect(docTabs.tab('handbook').root).toBeVisible();
    await clear(projectHead, panel);
    expect(await twoRows(projectHead)).toBe(true);
    const [head, line] = await Promise.all([projectHead.root.boundingBox(), docTabs.root.boundingBox()]);
    expect(line!.y).toBeCloseTo(head!.y + head!.height, 0);
  });

  test('the members unfold as the window widens', async ({ page, people, projects, projectHead, panel }) => {
    await page.setViewportSize({ width: 1330, height: 720 });
    const me = await people.signIn({ name: 'Test Person' });
    const { handles } = await six(people, me.handle!);
    const id = await projects.make({ name: makeUnique('Widen'), ticket: 'RB-12', members: handles, tasks: [LONG_STEP], notes: [note('one')] });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();
    await expect(projectHead.membersMore).toBeVisible();

    await page.setViewportSize({ width: 1700, height: 720 });
    await expect(projectHead.memberAvatars).toHaveCount(6);
    await expect(projectHead.membersMore).toHaveCount(0);
    await clear(projectHead, panel);
  });

  test('a draft’s chip, its members and its menu stay inside the head', async ({ page, people, projects, projectHead, panel }) => {
    await page.setViewportSize({ width: 1200, height: 720 });
    const me = await people.signIn({ name: 'Test Person' });
    const { handles } = await six(people, me.handle!);
    const id = await projects.make({
      name: `${makeUnique('Draft')} has a name long enough to fill a project’s head on its own`,
      state: 'draft',
      members: handles,
    });
    await projectHead.open(id);
    await expect(panel.root).toBeVisible();

    expect(await cut(projectHead.name)).toBe(true);
    expect(await cut(projectHead.draft)).toBe(false);
    await clear(projectHead, panel);
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
    await expect(page).toHaveURL(projectAddress(bId));
    await expect(projectHead.name).toHaveText(b);

    // Back and Forward press nothing on the page: only another project closes what is open.
    await projectHead.step.click();
    await expect(projectHead.plan).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(projectAddress(a));
    await expect(projectHead.step).toBeVisible();
    await expect(projectHead.plan).toHaveCount(0);

    await projectHead.notesButton.click();
    await expect(projectHead.notes).toBeVisible();
    await page.goForward();
    await expect(page).toHaveURL(projectAddress(bId));
    await expect(projectHead.step).toBeVisible();
    await expect(projectHead.notes).toHaveCount(0);
    await expect(projectHead.plan).toHaveCount(0);
  });
});

test.describe('The head on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('is one line: the drawer’s button, the name and the ticket, the switch without its label, the donut alone, the members, the notes’ button and the menu, with no repo or step button', async ({
    people,
    projects,
    projectHead,
    shell,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({
      name: makeUnique('Line'),
      ticket: 'PL-7',
      repo: 'pvginkel/Example',
      members: [me.handle!, 'ada'],
      tasks: [step('a', 'done'), step('b', 'in_progress')],
      notes: [note('one')],
    });
    await projectHead.open(id);

    for (const absent of [projectHead.repo, projectHead.step]) await expect(absent).toHaveCount(0);
    await expect(projectHead.autopilot).toHaveText('');
    await expect(projectHead.autopilot).toHaveAccessibleName('Auto pilot');
    await expect(projectHead.donut).toHaveText('');
    await expect(projectHead.donut).toHaveAttribute('title', '1 of 2 steps done · in progress: Step b');
    await expect(projectHead.donut).toHaveAccessibleName('The plan: 1 of 2 steps done · in progress: Step b');
    await expect(projectHead.donut.getByTestId('project.step.ring')).toBeVisible();
    await expect(projectHead.memberAvatars).toHaveCount(2);
    await expect(projectHead.membersMore).toHaveCount(0);

    const head = await boxOf(projectHead.root);
    expect(head.height).toBe(52);
    const parts = [
      shell.drawerToggle,
      projectHead.name,
      projectHead.ticket,
      projectHead.autopilot,
      projectHead.donut,
      projectHead.members,
      projectHead.notesButton,
      projectHead.menuButton,
    ];
    const boxes = await Promise.all(parts.map(boxOf));
    for (const [index, box] of boxes.entries()) {
      expect(box.y + box.height / 2, `part ${index}`).toBeCloseTo(head.y + head.height / 2, -1);
      if (index > 0) expect(box.x, `part ${index}`).toBeGreaterThanOrEqual(boxes[index - 1].x + boxes[index - 1].width - 0.5);
    }
    expect(boxes.at(-1)!.x + boxes.at(-1)!.width).toBeLessThanOrEqual(390);

    await projectHead.notesButton.tap();
    await expect(projectHead.notes.getByTestId('project.notes.list.note.summary')).toHaveText(['Summary one']);
    const notes = await boxOf(projectHead.notes);
    expect(notes.x).toBeGreaterThanOrEqual(0);
    expect(notes.x + notes.width).toBeLessThanOrEqual(390);
  });

  test('a tap on the donut shows the Plan tab', async ({ people, projects, projectHead, phoneTabs }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Donut'), members: [me.handle!], tasks: [step('a', 'in_progress')] });
    await projectHead.open(id);
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');

    await projectHead.donut.tap();
    await expect(phoneTabs.tab('plan')).toHaveAttribute('aria-selected', 'true');
    await expect(phoneTabs.plan.steps.getByTestId('project.plan.step.title')).toHaveText(['Step a']);
    await expect(projectHead.plan).toHaveCount(0);
    await projectHead.donut.tap();
    await expect(phoneTabs.tab('plan')).toHaveAttribute('aria-selected', 'true');
  });

  test('the members are two circles at most: the first member’s avatar, then the second’s, or a “+N” naming the rest on its tooltip and to a screen reader', async ({
    people,
    projects,
    projectHead,
  }) => {
    const me = await people.signIn({ name: 'Test Person' });
    const many = await projects.make({ name: makeUnique('Many'), members: [me.handle!, 'ada', 'ben'] });
    const two = await projects.make({ name: makeUnique('Two'), members: ['ada', 'ben'] });
    const one = await projects.make({ name: makeUnique('One'), members: [me.handle!] });

    await projectHead.open(many);
    await expect(projectHead.memberAvatars).toHaveText(['TP']);
    await expect(projectHead.membersMore).toHaveText('+2');
    await expect(projectHead.membersMore).toHaveAttribute('title', 'Ada Example, Ben Example');
    await expect(projectHead.membersMore).toHaveAccessibleName('2 more: Ada Example, Ben Example');
    const [first, more] = [await boxOf(projectHead.memberAvatars.first()), await boxOf(projectHead.membersMore)];
    expect(more.x).toBeCloseTo(first.x + first.width - 2, 1);
    expect(more.width).toBe(first.width);

    await projectHead.open(two);
    await expect(projectHead.memberAvatars).toHaveText(['AE', 'BE']);
    await expect(projectHead.membersMore).toHaveCount(0);

    await projectHead.open(one);
    await expect(projectHead.members.locator('.avatar')).toHaveText(['TP']);
  });

  test('the warning triangle stands after the switch while work briefed under its other setting is held', async ({ people, projects, projectHead }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Warned'), members: [me.handle!], autopilot: true, paused: true });
    const work = await projects.startWork(project, { title: 'Surveying', brief: 'Survey it.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(project, work)).state).toBe('held');
    await projectHead.open(project);

    await projectHead.autopilot.tap();
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
    await expect(projectHead.autopilotWarning).toBeVisible();
    const [autopilot, warning, donut] = await Promise.all([projectHead.autopilot, projectHead.autopilotWarning, projectHead.donut].map(boxOf));
    expect(warning.x).toBeGreaterThanOrEqual(autopilot.x + autopilot.width - 6.5);
    expect(donut.x).toBeGreaterThan(warning.x + warning.width);
    expect(warning.y + warning.height / 2).toBeCloseTo(autopilot.y + autopilot.height / 2, -1);
  });

  test('a tight head gives way in the name, cut to nothing, the drawer’s button and every other part keeping its size, the menu inside the head', async ({
    page,
    people,
    projects,
    projectHead,
    shell,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({
      name: `A rather long project name that cannot fit ${makeUnique('Tight')}`,
      ticket: 'PL-1234',
      members: [me.handle!, 'ada', 'ben'],
      tasks: [step('a', 'in_progress')],
      notes: [note('one')],
    });
    await projectHead.open(id);

    await expect(projectHead.menuButton).toBeVisible();
    const kept = [shell.drawerToggle, projectHead.ticket, projectHead.autopilot, projectHead.donut, projectHead.members, projectHead.notesButton, projectHead.menuButton];
    const widths = async () => Promise.all(kept.map(async (locator) => (await boxOf(locator)).width));
    const whole = await widths();
    expect(whole[0]).toBe(36);
    expect(await projectHead.name.evaluate((name) => name.scrollWidth > name.clientWidth)).toBe(true);
    const wide = await boxOf(projectHead.name);

    // A window as wide as the rest of the head: the name gives it every pixel, down to nothing.
    const rest = Math.ceil(390 - wide.width);
    await page.setViewportSize({ width: rest, height: 844 });
    await expect.poll(async () => (await boxOf(projectHead.name)).width).toBeLessThan(1);
    expect(await widths()).toEqual(whole);
    const menu = await boxOf(projectHead.menuButton);
    expect(menu.x + menu.width).toBeLessThanOrEqual(rest);
    expect((await boxOf(projectHead.root)).height).toBe(52);
  });

  test('its Draft chip’s word stands a pixel higher in its pill than a shared chip’s, the pill as high', async ({ people, projects, projectHead, timeline }) => {
    await draftChipAgainstShared(people, projects, projectHead, timeline);
  });

  test('a draft’s is its drawer’s button, its name and Draft chip, its members and its menu', async ({ people, projects, projectHead, shell }) => {
    const me = await people.signIn();
    const name = makeUnique('Draft');
    const id = await projects.make({ name, state: 'draft', members: [me.handle!] });
    await projectHead.open(id);

    await expect(projectHead.name).toHaveText(name);
    await expect(projectHead.draft).toHaveText('Draft');
    for (const absent of [projectHead.autopilot, projectHead.donut, projectHead.notesButton]) await expect(absent).toHaveCount(0);
    const head = await boxOf(projectHead.root);
    const parts = await Promise.all([shell.drawerToggle, projectHead.name, projectHead.draft, projectHead.members, projectHead.menuButton].map(boxOf));
    for (const box of parts) expect(box.y + box.height / 2).toBeCloseTo(head.y + head.height / 2, -1);
    expect(parts[4].x + parts[4].width).toBeLessThanOrEqual(390);
  });

  test('a finished project shows the Finished chip in the switch’s place, an archived one its chip after the name, each its icon alone, its word on the tooltip and to a screen reader', async ({
    people,
    projects,
    projectHead,
  }) => {
    const me = await people.signIn();
    const finished = await projects.make({ name: makeUnique('Done'), state: 'finished', members: [me.handle!], tasks: [step('a', 'done')] });
    const archived = await projects.make({ name: makeUnique('Archived'), archived: true, members: [me.handle!] });

    await projectHead.open(finished);
    await expect(projectHead.finished).toHaveText('Finished');
    await expect(projectHead.finished).toHaveAttribute('title', 'Finished');
    await expect(projectHead.finished.locator('svg')).toBeVisible();
    expect((await boxOf(projectHead.finished)).width).toBeLessThan(30);
    await expect(projectHead.autopilot).toHaveCount(0);
    await expect(projectHead.donut).toBeVisible();

    await projectHead.open(archived);
    await expect(projectHead.archived).toHaveText('Archived');
    await expect(projectHead.archived).toHaveAttribute('title', 'Archived');
    await expect(projectHead.archived.locator('svg')).toBeVisible();
    expect((await boxOf(projectHead.archived)).width).toBeLessThan(30);
    await expect(projectHead.autopilot).toBeDisabled();
    expect((await boxOf(projectHead.archived)).x).toBeGreaterThan((await boxOf(projectHead.name)).x);
  });

  test('an archived and a finished head with a ticket, three members and the notes’ button hold one line, the menu inside the head', async ({
    people,
    projects,
    projectHead,
  }) => {
    const me = await people.signIn();
    const parts = { ticket: 'PL-1234', members: [me.handle!, 'ada', 'ben'], tasks: [step('a', 'done')], notes: [note('one')] };
    const archived = await projects.make({ name: makeUnique('Shelved'), archived: true, ...parts });
    const finished = await projects.make({ name: makeUnique('Ended'), state: 'finished', ...parts });

    for (const id of [archived, finished]) {
      await projectHead.open(id);
      await expect(projectHead.menuButton).toBeVisible();
      await expect(projectHead.notesButton).toBeVisible();
      const head = await boxOf(projectHead.root);
      expect(head.height).toBe(52);
      const menu = await boxOf(projectHead.menuButton);
      expect(menu.x + menu.width).toBeLessThanOrEqual(390);
      expect(menu.y + menu.height / 2).toBeCloseTo(head.y + head.height / 2, -1);
    }
  });
});

async function boxOf(locator: Locator): Promise<{ x: number; y: number; width: number; height: number }> {
  return (await locator.boundingBox())!;
}

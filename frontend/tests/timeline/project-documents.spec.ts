/**
 * The project's handbook (F129.4) and its project document, `project.md` (F37.4), in the overlay,
 * each at its own address over the project's timeline (F97), as an attachment opens: rendered,
 * read only, no foot; *Empty* before the first save, Pilot's dots while a turn saves it (F35), and
 * "The document did not load" for a read that fails (F113). The handbook's button stands in the
 * head's icon group, left of the notes button (F2.3, F2.7); a draft has none, nor a handbook
 * (F129.2). A save shows live as it lands, Pilot's dots with it until the turn ends, the project
 * document's renaming the project, and once a stream that went down comes back up. On a phone it
 * is the whole screen (F98.3), and switching projects closes it (F1.6).
 */

import { randomUUID } from 'node:crypto';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { handbookAddress, projectDocumentAddress } from '../support/page-objects/overlay-page';

const HANDBOOK = '# Handbook\n\nHow the trip is planned.\n\n- We **always** pack light.\n- The van is booked a week ahead.\n';
const NOTE = { id: 'one', summary: 'Summary one', content: 'Content one' };

test.describe('The handbook', () => {
  test('a button in the head’s icon group, left of the notes button, opens it at its address in the overlay over the timeline: rendered, read only, no foot', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Handbook');
    const id = await projects.makeWithSession({ name, members: [me.handle!], notes: [NOTE] });
    const trip = await projects.place(id, { kind: 'notice', title: 'We leave on Friday', text: '# We leave on Friday\n' });
    await projects.saveProjectDocument(id, 'handbook', HANDBOOK);
    await projects.endTurn(id);
    await projectHead.open(id);

    await expect(projectHead.handbookButton).toHaveText('');
    await expect(projectHead.handbookButton).toHaveAttribute('aria-label', 'The handbook');
    const [members, handbook, notes] = await Promise.all(
      [projectHead.members, projectHead.handbookButton, projectHead.notesButton].map(async (locator) => (await locator.boundingBox())!),
    );
    expect(handbook.x).toBeGreaterThan(members.x + members.width);
    // Icon buttons side by side touch.
    expect(notes.x).toBeCloseTo(handbook.x + handbook.width, 0);

    await projectHead.handbookButton.click();
    await expect(page).toHaveURL(handbookAddress(id));
    await expect(overlay.root).toBeVisible();
    await expect(timeline.item(trip).root).toBeAttached();
    await expect(overlay.title).toHaveText('Handbook');
    await expect(overlay.project).toHaveText(name);
    await expect(overlay.role).toHaveText('Handbook');
    await expect(overlay.document).toContainText('How the trip is planned.');
    await expect(overlay.document.locator('li')).toHaveText(['We always pack light.', 'The van is booked a week ahead.']);
    await expect(overlay.document.locator('strong')).toHaveText('always');
    await expect(overlay.document.locator('h1')).toHaveCount(0);
    await expect(overlay.body.locator('input, textarea, select, button, [contenteditable]')).toHaveCount(0);
    await expect(overlay.foot).toHaveCount(0);
    await expect(overlay.empty).toHaveCount(0);
    await expect(overlay.writing).toHaveCount(0);

    await overlay.close.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${id}`);

    await projectHead.handbookButton.click();
    await expect(overlay.root).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${id}`);
  });

  test('reads Empty before its first save; a save shows on its next read, with Pilot’s dots while the turn runs, gone once a read finds it ended', async ({
    page,
    people,
    projects,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Born'), members: [me.handle!] });
    await overlay.openProjectDocument(id, 'handbook');

    await expect(overlay.title).toHaveText('Handbook');
    await expect(overlay.empty).toHaveText('Empty');
    await expect(overlay.document).toHaveCount(0);
    await expect(overlay.writing).toHaveCount(0);

    await projects.saveProjectDocument(id, 'handbook', HANDBOOK);
    await overlay.openProjectDocument(id, 'handbook');
    await expect(overlay.document).toContainText('How the trip is planned.');
    await expect(overlay.empty).toHaveCount(0);
    await expect(overlay.writing).toBeVisible();
    await expect(overlay.writing.locator('.avatar')).toHaveAttribute('title', 'Pilot');

    await projects.endTurn(id);
    await overlay.openProjectDocument(id, 'handbook');
    await expect(overlay.document).toContainText('How the trip is planned.');
    await expect(overlay.writing).toHaveCount(0);
    await expect(page).toHaveURL(handbookAddress(id));
  });

  test('a draft has none: no button in its head, and the handbook’s address reads “The document did not load”', async ({
    page,
    people,
    projects,
    projectHead,
    overlay,
  }) => {
    const me = await people.signIn();
    const draft = await projects.make({ name: makeUnique('Draft'), state: 'draft', members: [me.handle!], notes: [NOTE] });
    await projectHead.open(draft);
    await expect(projectHead.draft).toBeVisible();
    await expect(projectHead.handbookButton).toHaveCount(0);

    await page.goto(handbookAddress(draft));
    await expect(overlay.failed).toHaveText('The document did not load.');
    await expect(overlay.title).toHaveCount(0);
    await expect(overlay.foot).toHaveCount(0);
    await overlay.close.click();
    await expect(page).toHaveURL(`/projects/${draft}`);
  });
});

test.describe('The project document', () => {
  test('opens at its own address in the overlay over the timeline, read only: Empty as born with its title alone, then its prose once saved', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Recipes');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'notice', title: 'We leave on Friday', text: '# We leave on Friday\n' });
    await overlay.openProjectDocument(id, 'draft');

    await expect(page).toHaveURL(projectDocumentAddress(id));
    await expect(timeline.item(trip).root).toBeAttached();
    await expect(overlay.title).toHaveText(name);
    await expect(overlay.project).toHaveText(name);
    await expect(overlay.role).toHaveText('Project document');
    await expect(overlay.empty).toHaveText('Empty');

    await projects.saveProjectDocument(id, 'draft', `# ${name}\n\nA box for the family’s recipes, *searchable* by what is in the fridge.\n`);
    await overlay.openProjectDocument(id, 'draft');
    await expect(overlay.document).toHaveText('A box for the family’s recipes, searchable by what is in the fridge.');
    await expect(overlay.document.locator('em')).toHaveText('searchable');
    await expect(overlay.body.locator('input, textarea, select, button, [contenteditable]')).toHaveCount(0);
    await expect(overlay.foot).toHaveCount(0);
    await expect(overlay.writing).toBeVisible();

    await overlay.close.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${id}`);
  });

  test('reads a save that renames the project live, its title and the project’s name with it', async ({
    people,
    projects,
    projectHead,
    overlay,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Before'), members: [me.handle!] });
    await overlay.openProjectDocument(id, 'draft');
    await deploymentSse.ensureConnected();
    await expect(overlay.empty).toBeVisible();

    const renamed = makeUnique('After');
    await projects.saveProjectDocument(id, 'draft', `# ${renamed}\n\nThe new name says what it is.\n`);
    await expect(overlay.title).toHaveText(renamed);
    await expect(overlay.project).toHaveText(renamed);
    await expect(projectHead.name).toHaveText(renamed);
    await expect(overlay.document).toHaveText('The new name says what it is.');
  });

  test('reads “The document did not load” where its read fails: an address naming no project', async ({ page, people, overlay }) => {
    await people.signIn();
    await page.goto(projectDocumentAddress(randomUUID()));
    await expect(overlay.failed).toHaveText('The document did not load.');
    await expect(overlay.title).toHaveCount(0);
  });
});

test.describe('Live', () => {
  for (const role of ['handbook', 'draft'] as const) {
    test(`the ${role === 'handbook' ? 'handbook' : 'project document'} open in the overlay shows a save as it lands, Pilot’s dots with it, gone when the turn ends`, async ({
      people,
      projects,
      overlay,
      deploymentSse,
    }) => {
      const me = await people.signIn();
      const name = makeUnique('Live');
      const id = await projects.makeWithSession({ name, members: [me.handle!] });
      await overlay.openProjectDocument(id, role);
      await deploymentSse.ensureConnected();
      await expect(overlay.empty).toBeVisible();
      await expect(overlay.writing).toHaveCount(0);

      await projects.saveProjectDocument(id, role, role === 'handbook' ? HANDBOOK : `# ${name}\n\nHow the trip is planned.\n`);
      await expect(overlay.document).toContainText('How the trip is planned.');
      await expect(overlay.empty).toHaveCount(0);
      await expect(overlay.writing).toBeVisible();

      await projects.endTurn(id);
      await expect(overlay.writing).toHaveCount(0);
      await expect(overlay.document).toContainText('How the trip is planned.');
    });
  }
});

test.describe('A stream that comes back up', () => {
  for (const role of ['handbook', 'draft'] as const) {
    test(`reads again the ${role === 'handbook' ? 'handbook' : 'project document'} open in the overlay, saved while the stream was down`, async ({
      page,
      backendUrl,
      auth,
      people,
      projects,
      overlay,
      deploymentSse,
      toastHelper,
    }) => {
      const me = await people.signIn();
      const name = makeUnique('Down');
      const id = await projects.makeWithSession({ name, members: [me.handle!] });
      await overlay.openProjectDocument(id, role);
      await deploymentSse.ensureConnected();
      await expect(overlay.empty).toBeVisible();

      // The stream goes down and stays down: its next connect is refused, and the session check
      // that would open it again fails.
      const refusal = await page.request.post(`${backendUrl}/api/testing/sse/force-callback-error?status=403`);
      expect(refusal.status()).toBe(204);
      await auth.forceError(500);
      await page.evaluate(() => window.__sseForceReconnect!());
      await toastHelper.expectErrorToast(/refresh the page/i);
      expect((await deploymentSse.getStatus()).isConnected).toBe(false);

      // The save's event reaches no one: the stream is down.
      await projects.saveProjectDocument(id, role, role === 'handbook' ? HANDBOOK : `# ${name}\n\nHow the trip is planned.\n`);
      await deploymentSse.connect();
      await expect(overlay.document).toContainText('How the trip is planned.');
      await expect(overlay.empty).toHaveCount(0);
    });
  }
});

test.describe('On a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('the handbook is the whole screen, with no maximize, from the head’s button within the window', async ({
    people,
    projects,
    projectHead,
    shell,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Phone'), members: [me.handle!], notes: [NOTE] });
    await projects.saveProjectDocument(id, 'handbook', HANDBOOK);
    await projectHead.open(id);

    const button = (await projectHead.handbookButton.boundingBox())!;
    expect(button.x + button.width).toBeLessThanOrEqual(390);
    await projectHead.handbookButton.tap();
    await expect(overlay.document).toContainText('How the trip is planned.');
    const box = (await overlay.root.boundingBox())!;
    const app = (await shell.app.boundingBox())!;
    expect(box.x).toBe(0);
    expect(box.width).toBe(390);
    expect(box.y).toBe(app.y);
    expect(box.y + box.height).toBe(app.y + app.height);
    await expect(overlay.maximize).toBeHidden();
    await expect(overlay.close).toBeVisible();
  });

  test('switching projects from the drawer closes it', async ({ page, people, projects, projectList, shell, overlay }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('First'), members: [me.handle!] });
    const otherName = makeUnique('Second');
    const other = await projects.makeWithSession({ name: otherName, members: [me.handle!] });
    await overlay.openProjectDocument(id, 'handbook');
    await expect(overlay.root).toBeVisible();

    await shell.drawerToggle.click();
    await projectList.tab(otherName).click();
    await expect(page).toHaveURL(`/projects/${other}`);
    await expect(overlay.root).toHaveCount(0);
    await expect(overlay.backdrop).toHaveCount(0);
  });
});

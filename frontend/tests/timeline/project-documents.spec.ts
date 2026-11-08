/**
 * The project's handbook (F129.4) and its project document, `project.md` (F37.4), each at its own
 * address in its tab in the project's timeline's place (F97), as an attachment opens: rendered,
 * read only, no foot; *Empty* before the first save, Pilot's dots while a turn saves it (F35), and
 * "The document did not load" for a read that fails (F113). Its asks stand in their places, read
 * only (D1): an answered one closed, its answer and who gave it showing, an open one open, and
 * nothing in either to press; a text of asks alone is no longer *Empty*. The side panel's Documents
 * lists the handbook by its title right under the project document, opening it in its tab, and
 * the head has no button for it (F2.3); a draft's Documents has no row for it, nor a draft a
 * handbook (F129.2). A save shows live as it lands, Pilot's dots with
 * it until the turn ends, the project document's renaming the project, and once a stream that went
 * down comes back up. On a phone the Documents tab lists the handbook under the project document,
 * by its title, and neither the head nor the project's menu has it; it opens as a view, the whole
 * screen over the head and its drawer's button, with no maximize or cross (F98.4), its arrow back
 * taking it off, and switching projects closes it (F1.6). A link in either to the project's
 * attached material, by its path in the project's folder, opens the attachment where it hangs, the
 * draft's material on the opening, in a tab of its own, adding no entry, closing it showing the tab
 * before; on a phone a view pushed over the document's, Back showing the document where it was
 * read (F29.3). Any other link opens in a new browser tab, and one naming no attachment is its
 * words alone.
 */

import { randomUUID } from 'node:crypto';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { handbookAddress, projectDocumentAddress } from '../support/page-objects/overlay-page';
import { attachmentAddress } from '../support/page-objects/timeline-page';
import { projectAddress, type AttachedFile, type Projects } from '../support/projects';

const HANDBOOK = '# Handbook\n\nHow the trip is planned.\n\n- We **always** pack light.\n- The van is booked a week ahead.\n';
const NOTE = { id: 'one', summary: 'Summary one', content: 'Content one' };
const MAP: AttachedFile = { title: 'Camp map', filename: 'camp-map.md', content_type: 'text/markdown', content: '# The camp\n\nBy the lake.\n' };
const LIST: AttachedFile = { title: 'Packing list', filename: 'packing-list.md', content_type: 'text/markdown', content: '# Packing list\n\nThe stove.\n' };

/** The batch an attachment of the project came in, as its timeline reads it. */
async function batchOf(projects: Projects, projectId: string, attachmentId: string): Promise<number> {
  const { items } = await projects.timeline(projectId);
  return items.flatMap((item) => item.attachments).find((attachment) => attachment.id === attachmentId)!.batch;
}

test.describe('The handbook', () => {
  test('its row in the side panel’s Documents, by its title right under the project document, opens it at its address in its tab: rendered, read only, no foot', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
    overlay,
    docTabs,
    panel,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Handbook');
    const id = await projects.makeWithSession({ name, members: [me.handle!], notes: [NOTE] });
    const trip = await projects.place(id, { kind: 'notice', title: 'We leave on Friday', text: '# We leave on Friday\n' });
    await projects.saveProjectDocument(id, 'handbook', HANDBOOK);
    await projects.endTurn(id);
    await projectHead.open(id);

    expect(await projectHead.controls()).toEqual(['project.autopilot', 'project.step', 'project.notes.button', 'project.menu.button']);
    await panel.documentsTab.click();
    await expect(panel.handbook.title).toHaveText('Handbook');
    await expect(panel.handbook.sub).toHaveText('Handbook');
    await expect(panel.body.locator('.doc-row').first()).toHaveAttribute('data-testid', 'panel.project-document');
    await expect(panel.body.locator('.doc-row').nth(1)).toHaveAttribute('data-testid', 'panel.handbook');
    const [projectDocument, handbook] = [await panel.projectDocument.root.boundingBox(), await panel.handbook.root.boundingBox()];
    expect(handbook!.y).toBeCloseTo(projectDocument!.y + projectDocument!.height, 0);

    await panel.handbook.root.click();
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

    await docTabs.tab('handbook').close.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));

    await panel.handbook.root.click();
    await expect(overlay.root).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(overlay.root).toBeVisible();
    await expect(page).toHaveURL(handbookAddress(id));
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

  test('a draft has none: no row in its Documents, and the handbook’s address reads “The document did not load”', async ({
    page,
    people,
    projects,
    projectHead,
    overlay,
    docTabs,
    panel,
  }) => {
    const me = await people.signIn();
    const draft = await projects.make({ name: makeUnique('Draft'), state: 'draft', members: [me.handle!], notes: [NOTE] });
    await projectHead.open(draft);
    await expect(projectHead.draft).toBeVisible();
    await panel.documentsTab.click();
    await expect(panel.headings).toHaveText(['Attachments']);
    await expect(panel.handbook.root).toHaveCount(0);

    await page.goto(handbookAddress(draft));
    await expect(overlay.failed).toHaveText('The document did not load.');
    await expect(overlay.title).toHaveCount(0);
    await expect(overlay.foot).toHaveCount(0);
    await docTabs.tab('handbook').close.click();
    await expect(page).toHaveURL(projectAddress(draft));
  });
});

test.describe('The project document', () => {
  test('opens at its own address in its tab in the timeline’s place, read only: Empty as born with its title alone, then its prose once saved', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    docTabs,
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

    await docTabs.tab('project-document').close.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));
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

/** Nothing in the overlay's body takes a click or a word. */
const PRESSABLE = 'button:enabled, input:enabled, textarea:enabled, select:enabled, [contenteditable]';

test.describe('Its asks', () => {
  test('the handbook draws each ask in its place, read only: an answer closed with who gave it and when, an open ask open, nothing to press', async ({
    people,
    projects,
    overlay,
  }) => {
    const me = await people.signIn({ name: 'Ada Example' });
    const id = await projects.makeWithSession({ name: makeUnique('Asks'), members: [me.handle!] });
    await projects.saveProjectDocument(
      id,
      'handbook',
      [
        '# Handbook',
        '',
        'How the trip is planned.',
        '',
        '```decision id=D1',
        'options:',
        '  - Train: the night train to Vienna',
        '  - Car',
        'recommend: Train',
        'answer: Car',
        'by: agent',
        'at: 2026-10-20T09:00:00Z',
        '```',
        '',
        'How long we stay.',
        '',
        '```question id=Q1',
        'default: Two weeks',
        '```',
        '',
        '```action id=A1',
        '```',
        '',
      ].join('\n'),
    );
    await projects.endTurn(id);
    await projects.answerProjectDocument(id, 'handbook', 'Q1', 'Ten days', me.handle!);
    await overlay.openProjectDocument(id, 'handbook');

    await expect(overlay.empty).toHaveCount(0);
    await expect(overlay.document.locator('.prose')).toHaveText(['How the trip is planned.', 'How long we stay.']);
    await expect(overlay.blocks).toHaveCount(3);
    // Each ask in its place among the prose: a part is its prose's words, or its block's id.
    expect(
      await overlay.document
        .locator(':scope > *')
        .evaluateAll((parts) => parts.map((part) => part.getAttribute('data-block-id') ?? part.textContent?.trim())),
    ).toEqual(['How the trip is planned.', 'D1', 'How long we stay.', 'Q1', 'A1']);

    // Pilot's answer, closed: the chosen row alone, which opens nothing, Pilot's avatar and the time.
    const pilots = overlay.blockAt('D1');
    await expect(pilots.root).toHaveAttribute('data-closed', 'true');
    await expect(pilots.kind).toHaveText('Decision');
    await expect(pilots.answered).toBeVisible();
    await expect(pilots.options).toHaveCount(1);
    await expect(pilots.option('Car')).toBeDisabled();
    await expect(pilots.option('Car')).not.toHaveAttribute('title');
    await expect(pilots.who.locator('.avatar')).toHaveAttribute('title', 'Pilot');
    await expect(pilots.time).toBeVisible();
    await expect(pilots.toggle).toHaveCount(0);
    await expect(pilots.discuss).toHaveCount(0);

    // The person's answer, closed: the words, the person's avatar.
    const persons = overlay.blockAt('Q1');
    await expect(persons.root).toHaveAttribute('data-closed', 'true');
    await expect(persons.answered).toBeVisible();
    await expect(persons.said).toHaveText('Ten days');
    await expect(persons.who.locator('.avatar')).toHaveAttribute('title', 'Ada Example');
    await expect(persons.answerField).toHaveCount(0);
    await expect(persons.toggle).toHaveCount(0);
    await expect(persons.discuss).toHaveCount(0);

    // Open: its controls stand, disabled.
    const open = overlay.blockAt('A1');
    await expect(open.root).toHaveAttribute('data-closed', 'false');
    await expect(open.root).toHaveClass(/\bopen\b/);
    await expect(open.kind).toHaveText('Action');
    await expect(open.answered).toHaveCount(0);
    await expect(open.paste).toBeDisabled();
    await expect(open.done).toBeDisabled();
    await expect(open.discuss).toHaveCount(0);

    await expect(overlay.body.locator(PRESSABLE)).toHaveCount(0);
  });

  test('a project document of asks alone is drawn, not Empty: a confirmation and a question left open stand open, a decision Pilot settled and a deferral read closed', async ({
    people,
    projects,
    overlay,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Only asks');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    await projects.saveProjectDocument(
      id,
      'draft',
      [
        `# ${name}`,
        '',
        '```decision id=C1',
        'type: confirmation',
        'proposal: Book the night train',
        'because: auto-pilot-off',
        '```',
        '',
        '```question id=Q1',
        'default: Two weeks',
        '```',
        '',
        '```decision id=D1',
        'proposal: Pack light',
        'answer: Agree',
        'by: agent',
        '```',
        '',
        '```decision id=D2',
        'options:',
        '  - Dome',
        '  - Tunnel',
        'answer: deferred',
        'by: agent',
        'to: plan',
        '```',
        '',
      ].join('\n'),
    );
    await projects.endTurn(id);
    await overlay.openProjectDocument(id, 'draft');

    await expect(overlay.title).toHaveText(name);
    await expect(overlay.empty).toHaveCount(0);
    await expect(overlay.document.locator('.prose')).toHaveCount(0);
    await expect(overlay.blocks).toHaveCount(4);

    const confirm = overlay.blockAt('C1');
    await expect(confirm.root).toHaveAttribute('data-closed', 'false');
    await expect(confirm.kind).toHaveText('Confirm');
    await expect(confirm.root.getByTestId('timeline.confirm.proposal')).toHaveText('Book the night train');
    await expect(confirm.yes).toBeDisabled();
    await expect(confirm.no).toBeDisabled();

    const question = overlay.blockAt('Q1');
    await expect(question.root).toHaveAttribute('data-closed', 'false');
    await expect(question.answerField).toBeDisabled();
    await expect(question.answerField).toHaveAttribute('placeholder', 'Default: Two weeks');
    await expect(question.answerSend).toBeDisabled();

    const agreed = overlay.blockAt('D1');
    await expect(agreed.root).toHaveAttribute('data-closed', 'true');
    await expect(agreed.options).toHaveText(['Pack light']);
    await expect(agreed.options).toBeDisabled();
    await expect(agreed.who.locator('.avatar')).toHaveAttribute('title', 'Pilot');

    const deferred = overlay.blockAt('D2');
    await expect(deferred.root).toHaveAttribute('data-closed', 'true');
    await expect(deferred.deferred).toContainText("Deferred to the project's end");
    await expect(deferred.options).toHaveCount(0);

    await expect(overlay.body.locator(PRESSABLE)).toHaveCount(0);
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

test.describe('A link to the project’s attached material', () => {
  test('in the project document opens the attachment where it hangs in a tab of its own, adding no entry, closing it showing the project document’s, the draft’s material on the opening; any other link opens in a new browser tab, a ticket id linked still, and one naming no attachment is its words alone', async ({
    page,
    backendUrl,
    links,
    people,
    projects,
    overlay,
    docTabs,
  }) => {
    await links.set({ ticket_url_template: `${backendUrl}/tickets/{id}` });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Linked'), members: [me.handle!] });
    const camp = await projects.place(id, { kind: 'notice', title: 'The camp', text: 'What we saw.\n' });
    const opening = (await projects.timeline(id)).items.find((item) => item.kind === 'opening')!.id;
    const [map] = await projects.attach(camp, [MAP]);
    // The draft's material, which Create project hangs on the opening.
    const [list] = await projects.attach(opening, [LIST]);
    const [mapBatch, listBatch] = [await batchOf(projects, id, map), await batchOf(projects, id, list)];
    await projects.saveProjectDocument(
      id,
      'draft',
      `# Linked\n\nThe camp is on [the map](attachments/${mapBatch}/camp-map.md), what we take on [the list](./attachments/${listBatch}/packing-list.md), the rest on [the site](https://example.com/site), [the old map](attachments/${mapBatch}/old-map.md) and in RB-12.\n`,
    );
    await projects.endTurn(id);
    await overlay.openProjectDocument(id, 'draft');

    await expect(overlay.document).toHaveText('The camp is on the map, what we take on the list, the rest on the site, the old map and in RB-12.');
    await expect(overlay.document.getByRole('link')).toHaveText(['the map', 'the list', 'the site', 'RB-12']);
    await expect(overlay.materialLinks).toHaveText(['the map', 'the list']);
    await expect(overlay.materialLinks.first()).not.toHaveAttribute('target');
    const site = overlay.document.getByRole('link', { name: 'the site' });
    await expect(site).toHaveAttribute('href', 'https://example.com/site');
    await expect(site).toHaveAttribute('target', '_blank');
    const ticket = overlay.document.getByRole('link', { name: 'RB-12' });
    await expect(ticket).toHaveAttribute('href', `${backendUrl}/tickets/RB-12`);
    await expect(ticket).toHaveAttribute('target', '_blank');

    const entries = await page.evaluate(() => history.length);
    await overlay.materialLinks.filter({ hasText: 'the map' }).click();
    await expect(page).toHaveURL(attachmentAddress(id, camp, map));
    await expect(overlay.title).toHaveText('Camp map');
    await expect(overlay.sub).toHaveText('Attachment of “The camp”');
    await expect(overlay.attachment.prose).toContainText('By the lake.');
    await expect(docTabs.attachment(map).show).toHaveAttribute('aria-selected', 'true');
    expect(await docTabs.keys()).toEqual(['project-document', `attachment ${map}`]);
    expect(await page.evaluate(() => history.length)).toBe(entries);

    await docTabs.attachment(map).close.click();
    await expect(page).toHaveURL(projectDocumentAddress(id));
    await expect(docTabs.tab('project-document').show).toHaveAttribute('aria-selected', 'true');
    await expect(overlay.role).toHaveText('Project document');

    await overlay.materialLinks.filter({ hasText: 'the list' }).click();
    await expect(page).toHaveURL(attachmentAddress(id, opening, list));
    await expect(overlay.title).toHaveText('Packing list');
    await expect(overlay.attachment.prose).toContainText('The stove.');
    expect(await docTabs.keys()).toEqual(['project-document', `attachment ${list}`]);
    expect(await page.evaluate(() => history.length)).toBe(entries);
  });

  test('in the handbook opens the attachment in a tab of its own, closing it showing the handbook’s', async ({ page, people, projects, overlay, docTabs }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Linked'), members: [me.handle!] });
    const camp = await projects.place(id, { kind: 'notice', title: 'The camp', text: 'What we saw.\n' });
    const [map] = await projects.attach(camp, [MAP]);
    await projects.saveProjectDocument(id, 'handbook', `# How we travel\n\nWe camp where [the map](attachments/${await batchOf(projects, id, map)}/camp-map.md) says.\n`);
    await projects.endTurn(id);
    await overlay.openProjectDocument(id, 'handbook');

    await overlay.materialLinks.click();
    await expect(page).toHaveURL(attachmentAddress(id, camp, map));
    await expect(overlay.title).toHaveText('Camp map');
    expect(await docTabs.keys()).toEqual(['handbook', `attachment ${map}`]);
    await docTabs.attachment(map).close.click();
    await expect(page).toHaveURL(handbookAddress(id));
    await expect(overlay.title).toHaveText('How we travel');
  });
});

test.describe('On a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('the handbook’s link to the project’s attached material opens the attachment as a view pushed over the handbook’s; Back shows the handbook where it was read, after the five minutes its read is kept unread too', async ({
    page,
    people,
    projects,
    overlay,
    phoneTabs,
  }) => {
    await page.clock.install();
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Linked'), members: [me.handle!] });
    const camp = await projects.place(id, { kind: 'notice', title: 'The camp', text: 'What we saw.\n' });
    const [map] = await projects.attach(camp, [MAP]);
    const paragraphs = Array.from({ length: 60 }, (_, index) => `Paragraph ${index + 1} of the handbook.`).join('\n\n');
    const batch = await batchOf(projects, id, map);
    await projects.saveProjectDocument(id, 'handbook', `# How we travel\n\n${paragraphs}\n\nWe camp where [the map](attachments/${batch}/camp-map.md) says.\n`);
    await projects.endTurn(id);
    await overlay.openProjectDocument(id, 'handbook');
    await expect(overlay.document).toContainText('Paragraph 60 of the handbook.');
    await overlay.body.evaluate((body) => body.scrollTo({ top: body.scrollHeight }));
    await expect.poll(() => overlay.scrollTop()).toBeGreaterThan(0);
    const read = await overlay.scrollTop();

    await overlay.materialLinks.tap();
    await expect(page).toHaveURL(attachmentAddress(id, camp, map));
    await expect(overlay.title).toHaveText('Camp map');
    await expect(overlay.back).toBeVisible();
    expect(await overlay.scrollTop()).toBe(0);

    // Past the five minutes a query no one reads is kept for.
    await page.clock.fastForward('06:00');
    await overlay.back.tap();
    await expect(page).toHaveURL(handbookAddress(id));
    await expect(overlay.document).toContainText('Paragraph 60 of the handbook.');
    await expect.poll(() => overlay.scrollTop()).toBe(read);
    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
  });

  test('Back from the attachment shows the handbook at its end where it reads shorter than where it was read, after the five minutes its read is kept unread', async ({
    page,
    people,
    projects,
    overlay,
  }) => {
    await page.clock.install();
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Linked'), members: [me.handle!] });
    const camp = await projects.place(id, { kind: 'notice', title: 'The camp', text: 'What we saw.\n' });
    const [map] = await projects.attach(camp, [MAP]);
    const batch = await batchOf(projects, id, map);
    const handbook = (count: number) =>
      `# How we travel\n\n${Array.from({ length: count }, (_, index) => `Paragraph ${index + 1} of the handbook.`).join('\n\n')}\n\nWe camp where [the map](attachments/${batch}/camp-map.md) says.\n`;
    await projects.saveProjectDocument(id, 'handbook', handbook(60));
    await projects.endTurn(id);
    await overlay.openProjectDocument(id, 'handbook');
    await expect(overlay.document).toContainText('Paragraph 60 of the handbook.');
    await overlay.body.evaluate((body) => body.scrollTo({ top: body.scrollHeight }));
    await expect.poll(() => overlay.scrollTop()).toBeGreaterThan(0);
    const read = await overlay.scrollTop();

    await overlay.materialLinks.tap();
    await expect(overlay.title).toHaveText('Camp map');
    await projects.saveProjectDocument(id, 'handbook', handbook(30));
    await projects.endTurn(id);
    // Past the five minutes a query no one reads is kept for.
    await page.clock.fastForward('06:00');
    await overlay.back.tap();
    await expect(page).toHaveURL(handbookAddress(id));
    await expect(overlay.document).toContainText('Paragraph 30 of the handbook.');
    await expect(overlay.document).not.toContainText('Paragraph 31 of the handbook.');
    const end = await overlay.body.evaluate((body) => body.scrollHeight - body.clientHeight);
    expect(end).toBeGreaterThan(0);
    expect(end).toBeLessThan(read);
    await expect.poll(() => overlay.scrollTop()).toBe(end);
  });

  test('the Documents tab lists the handbook by its title right under the project document, opening it as a view, the whole screen with no maximize or cross; neither the head nor the project’s menu has it, nor a draft’s Documents', async ({
    page,
    people,
    projects,
    projectHead,
    shell,
    overlay,
    panel,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Phone'), members: [me.handle!], notes: [NOTE] });
    await projects.saveProjectDocument(id, 'handbook', '# How we travel\n\nHow the trip is planned.\n');
    const draft = await projects.make({ name: makeUnique('Draft'), state: 'draft', members: [me.handle!] });
    await projectHead.open(id);

    expect(await projectHead.controls()).toEqual(['shell.drawer-toggle', 'project.autopilot', 'project.donut', 'project.notes.button', 'project.menu.button']);
    await projectHead.menuButton.tap();
    await expect(projectHead.menuItems.first()).toBeVisible();
    await expect(projectHead.menuItems.filter({ hasText: /handbook/i })).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(projectHead.menu).toHaveCount(0);

    await phoneTabs.tab('documents').tap();
    await expect(panel.handbook.title).toHaveText('How we travel');
    await expect(panel.handbook.sub).toHaveText('Handbook');
    await expect(panel.body.locator('.doc-row').first()).toHaveAttribute('data-testid', 'panel.project-document');
    await expect(panel.body.locator('.doc-row').nth(1)).toHaveAttribute('data-testid', 'panel.handbook');
    const [projectDocument, handbook] = [await panel.projectDocument.root.boundingBox(), await panel.handbook.root.boundingBox()];
    expect(handbook!.y).toBeCloseTo(projectDocument!.y + projectDocument!.height, 0);

    await panel.handbook.root.tap();
    await expect(page).toHaveURL(handbookAddress(id));
    await expect(overlay.title).toHaveText('How we travel');
    await expect(overlay.document).toContainText('How the trip is planned.');
    const box = (await overlay.root.boundingBox())!;
    const app = (await shell.app.boundingBox())!;
    expect(box.x).toBe(0);
    expect(box.width).toBe(390);
    expect(box.y).toBe(app.y);
    expect(box.y + box.height).toBe(app.y + app.height);
    await expect(overlay.maximize).toHaveCount(0);
    await expect(overlay.close).toHaveCount(0);
    await expect(overlay.back).toBeVisible();

    await projectHead.open(draft);
    await phoneTabs.tab('documents').tap();
    await expect(panel.noAttachments).toBeVisible();
    await expect(panel.projectDocument.root).toHaveCount(0);
    await expect(panel.handbook.root).toHaveCount(0);
  });

  test('lies over the head and its drawer’s button, which its arrow back gives back to switch projects', async ({
    page,
    people,
    projects,
    projectList,
    shell,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('First'), members: [me.handle!] });
    const otherName = makeUnique('Second');
    const other = await projects.makeWithSession({ name: otherName, members: [me.handle!] });
    await overlay.openProjectDocument(id, 'handbook');
    await expect(overlay.root).toBeVisible();

    // It lies over the head, the drawer's button under it, with no top bar's to open it from.
    expect(
      await shell.drawerToggle.evaluate((button) => {
        const box = button.getBoundingClientRect();
        return button.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
      }),
    ).toBe(false);
    await overlay.back.click();
    await expect(overlay.root).toHaveCount(0);

    await shell.drawerToggle.click();
    await projectList.tab(otherName).click();
    await expect(page).toHaveURL(projectAddress(other));
    await expect(overlay.root).toHaveCount(0);
    await expect(overlay.backdrop).toHaveCount(0);
  });
});

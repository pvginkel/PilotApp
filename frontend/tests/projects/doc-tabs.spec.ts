/**
 * The desktop's documents in tabs (F28.1, F28.4, F28.5, F28.8, F97, F110): what opens as a
 * document opens as a tab in the timeline's place, the side panel beside it, the tab line the
 * head's last row while one is open — the timeline first and never closed, a tab per document at
 * the line's end in the order opened, a document already open showing its tab, each tab's cross
 * and the middle button closing it, *Close all* at its far right, the line scrolling where the
 * tabs do not fit — and hidden once the last one closes. Closing the tab showing shows the one
 * that showed before it; Done closes its tab; Esc closes none; a tab has no maximize, backdrop or
 * cross. An attachment is a tab of its own, its document a link in its head. Each tab keeps its
 * scroll while another shows, the timeline's included. The address follows the tab showing, a
 * tab's change replacing the browser's entry, and a document's address reached cold opens its
 * tab. A draft's first tab is its definition chat.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { documentAddress, documentAttachmentAddress, handbookAddress, projectDocumentAddress } from '../support/page-objects/overlay-page';
import { addressOf, attachmentAddress } from '../support/page-objects/timeline-page';
import type { AttachedFile } from '../support/projects';

const WORDS = (count: number) => Array.from({ length: count }, (_, index) => `word${index}`).join(' ');
const TENT = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const PITCH = '```question id=Q1\n```\n';
/** A document long enough to be a card on the timeline, whose Open opens it. */
const card = (title: string) => `---\ntitle: ${title}\n---\n\n${WORDS(160)}\n\n## Which tent?\n\n${TENT}\n## Where do we pitch?\n\n${PITCH}`;
const LONG_TEXT = (title: string) =>
  `---\ntitle: ${title}\n---\n\n${Array.from({ length: 40 }, (_, index) => `Paragraph ${index + 1} of ${title}.`).join('\n\n')}\n`;
const NOTES: AttachedFile = { title: 'Tent notes', filename: 'tent-notes.md', content_type: 'text/markdown', content: '# The tents we looked at\n' };

test.describe('Documents in tabs', () => {
  test('a document opens as a tab in the timeline’s place, the side panel beside it, under the tab line, the head’s last row: the timeline first, a tab per document in the order opened, one already open showing its tab', async ({
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
    const id = await projects.makeWithSession({ name: makeUnique('Tabs'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: card('The trip') });
    const route = await projects.place(id, { kind: 'document', title: 'The route', text: card('The route') });
    await timeline.open(id);
    await expect(docTabs.root).toHaveCount(0);
    const feed = (await timeline.root.boundingBox())!;

    await timeline.item(trip).card.open.click();
    await expect(page).toHaveURL(documentAddress(id, trip));
    await expect(docTabs.first).toHaveText('Timeline');
    await expect(docTabs.first).toHaveAttribute('aria-selected', 'false');
    expect(await docTabs.keys()).toEqual([`document ${trip}`]);
    await expect(docTabs.document(trip).title).toHaveText('The trip');
    await expect(docTabs.document(trip).root).toHaveAttribute('title', 'The trip');
    await expect(docTabs.document(trip).show).toHaveAttribute('aria-selected', 'true');
    await expect(overlay.title).toHaveText('The trip');
    await expect(overlay.root).toHaveAttribute('role', 'tabpanel');

    // The line stands under the head's rows, and the tab takes what the timeline took under it.
    const head = (await projectHead.root.boundingBox())!;
    const line = (await docTabs.root.boundingBox())!;
    expect(line.y).toBeCloseTo(head.y + head.height, 0);
    const tab = (await overlay.root.boundingBox())!;
    const side = (await panel.root.boundingBox())!;
    expect(tab.x).toBe(feed.x);
    expect(tab.y).toBeCloseTo(line.y + line.height, 0);
    expect(tab.x + tab.width).toBe(side.x);
    expect(tab.y + tab.height).toBe(feed.y + feed.height);
    // The timeline stays drawn under it, taking no focus.
    await expect(timeline.root).toHaveAttribute('inert', '');

    await docTabs.first.click();
    await expect(page).toHaveURL(`/projects/${id}`);
    await expect(overlay.root).toHaveCount(0);
    await expect(docTabs.first).toHaveAttribute('aria-selected', 'true');
    await timeline.item(route).card.open.click();
    expect(await docTabs.keys()).toEqual([`document ${trip}`, `document ${route}`]);
    await expect(overlay.title).toHaveText('The route');

    // Opened again, a document already open shows its tab, at the line's end no second one.
    await docTabs.first.click();
    await timeline.item(trip).card.open.click();
    expect(await docTabs.keys()).toEqual([`document ${trip}`, `document ${route}`]);
    await expect(docTabs.document(trip).show).toHaveAttribute('aria-selected', 'true');
    await expect(overlay.title).toHaveText('The trip');

    await docTabs.document(route).show.click();
    await expect(page).toHaveURL(documentAddress(id, route));
    await expect(overlay.title).toHaveText('The route');
  });

  test('closing the tab showing shows the one that showed before it, the middle button closes a tab, Close all every one, and the line hides once the last closes', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    docTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Close'), members: [me.handle!] });
    const [a, b, c] = await Promise.all(
      ['Alpha', 'Bravo', 'Charlie'].map((title) => projects.place(id, { kind: 'document', title, text: card(title) })),
    );
    await timeline.open(id);
    await timeline.item(a).card.open.click();
    for (const each of [b, c]) {
      await docTabs.first.click();
      await timeline.item(each).card.open.click();
    }
    // Shown in the order a, c, b: closing b goes back to c, then to a.
    await docTabs.document(a).show.click();
    await docTabs.document(c).show.click();
    await docTabs.document(b).show.click();
    await docTabs.document(b).close.click();
    await expect(page).toHaveURL(documentAddress(id, c));
    await expect(overlay.title).toHaveText('Charlie');
    expect(await docTabs.keys()).toEqual([`document ${a}`, `document ${c}`]);
    // The cross took its tab away under the focus: the tab showing has it.
    await expect(docTabs.document(c).show).toBeFocused();

    // Closing a tab that is not showing leaves the tab showing as it is.
    await docTabs.document(a).root.click({ button: 'middle' });
    expect(await docTabs.keys()).toEqual([`document ${c}`]);
    await expect(page).toHaveURL(documentAddress(id, c));
    await expect(overlay.title).toHaveText('Charlie');

    await docTabs.document(c).close.click();
    await expect(page).toHaveURL(`/projects/${id}`);
    await expect(overlay.root).toHaveCount(0);
    await expect(docTabs.root).toHaveCount(0);

    await timeline.item(a).card.open.click();
    await docTabs.first.click();
    await timeline.item(b).card.open.click();
    await expect(docTabs.closeAll).toHaveAttribute('aria-label', 'Close all documents');
    await docTabs.closeAll.click();
    await expect(docTabs.root).toHaveCount(0);
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${id}`);
  });

  test('Done closes its tab, showing the one before it; Esc closes none; a tab has no maximize, backdrop or cross of its own', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    docTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Done'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: card('The trip') });
    await timeline.open(id);
    await timeline.item(trip).card.open.click();

    await expect(overlay.maximize).toHaveCount(0);
    await expect(overlay.close).toHaveCount(0);
    await expect(overlay.backdrop).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(overlay.root).toBeVisible();
    await expect(page).toHaveURL(documentAddress(id, trip));

    await overlay.blockAt('D1').option('Tunnel').click();
    await overlay.blockAt('Q1').answerField.fill('By the lake');
    await overlay.blockAt('Q1').answerSend.click();
    await overlay.send.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(docTabs.root).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${id}`);
    await expect(timeline.item(trip).root).toHaveAttribute('data-state', 'done');
  });

  test('the address follows the tab showing, each change replacing the browser’s entry, so that Back leaves the project; a document’s address reached cold opens its tab', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    docTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Address'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: card('The trip') });
    const route = await projects.place(id, { kind: 'document', title: 'The route', text: card('The route') });
    await page.goto('/profile');
    await timeline.open(id);

    await timeline.item(trip).card.open.click();
    await expect(page).toHaveURL(documentAddress(id, trip));
    await docTabs.first.click();
    await expect(page).toHaveURL(`/projects/${id}`);
    await timeline.item(route).card.open.click();
    await docTabs.document(trip).show.click();
    await expect(page).toHaveURL(documentAddress(id, trip));
    // A segment of a card opens its document at the block's address, its tab showing.
    await docTabs.first.click();
    await timeline.item(route).segment('D1').click();
    await expect(page).toHaveURL(addressOf(id, route, 'D1'));
    await expect(docTabs.document(route).show).toHaveAttribute('aria-selected', 'true');
    await expect(overlay.title).toHaveText('The route');

    await page.goBack();
    await expect(page).toHaveURL('/profile');

    await page.goto(documentAddress(id, route));
    await expect(docTabs.document(route).show).toHaveAttribute('aria-selected', 'true');
    await expect(overlay.title).toHaveText('The route');
  });

  test('each tab keeps its scroll while another shows, the timeline’s included; one closed and opened again starts at its top', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    docTabs,
    panel,
  }) => {
    await page.setViewportSize({ width: 1280, height: 520 });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Scroll'), members: [me.handle!] });
    const items: string[] = [];
    for (const title of ['One', 'Two', 'Three', 'Four', 'Five']) items.push(await projects.place(id, { kind: 'document', title, text: card(title) }));
    const long = await projects.place(id, { kind: 'document', title: 'The long trip', text: LONG_TEXT('The long trip') });
    const other = await projects.place(id, { kind: 'document', title: 'The other trip', text: LONG_TEXT('The other trip') });
    await timeline.open(id);
    const scrollOf = () => timeline.root.evaluate((feed) => feed.scrollTop);
    await timeline.root.evaluate((feed) => feed.scrollTo({ top: 400 }));
    await expect.poll(scrollOf).toBe(400);

    await timeline.item(items[1]).card.open.click();
    await docTabs.first.click();
    expect(await scrollOf()).toBe(400);
    await panel.documentsTab.click();
    await panel.document(long).root.click();
    await expect(overlay.document).toContainText('Paragraph 40 of The long trip.');
    await overlay.body.evaluate((body) => body.scrollTo({ top: 300 }));
    await expect.poll(() => overlay.scrollTop()).toBe(300);
    await panel.document(other).root.click();
    await expect(overlay.document).toContainText('Paragraph 40 of The other trip.');
    await overlay.body.evaluate((body) => body.scrollTo({ top: 120 }));
    await expect.poll(() => overlay.scrollTop()).toBe(120);

    await docTabs.document(long).show.click();
    await expect(overlay.title).toHaveText('The long trip');
    expect(await overlay.scrollTop()).toBe(300);
    await docTabs.document(other).show.click();
    await expect(overlay.title).toHaveText('The other trip');
    expect(await overlay.scrollTop()).toBe(120);
    await docTabs.first.click();
    expect(await scrollOf()).toBe(400);

    await docTabs.document(long).close.click();
    await panel.document(long).root.click();
    await expect(overlay.title).toHaveText('The long trip');
    expect(await overlay.scrollTop()).toBe(0);
  });

  test('an attachment is a tab of its own, “Attachment of <item>” in its head, its document a link there that shows the document’s tab', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    docTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Attachment'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: card('The trip') });
    const notice = await projects.place(id, { kind: 'notice', title: 'The camp', text: 'What we saw.\n' });
    const [notes] = await projects.attach(trip, [NOTES]);
    const [map] = await projects.attach(notice, [{ ...NOTES, title: 'Camp map', filename: 'camp-map.md', content: '# The camp\n' }]);
    await timeline.open(id);

    await timeline.item(trip).card.open.click();
    await overlay.attachmentChip(notes).click();
    await expect(page).toHaveURL(documentAttachmentAddress(id, trip, notes));
    expect(await docTabs.keys()).toEqual([`document ${trip}`, `attachment ${notes}`]);
    await expect(docTabs.attachment(notes).title).toHaveText('Tent notes');
    await expect(overlay.title).toHaveText('Tent notes');
    await expect(overlay.sub).toHaveText('Attachment of “The trip”');
    await expect(overlay.back).toHaveCount(0);
    await expect(overlay.documentLink).toHaveAttribute('title', 'Open the document');
    await overlay.documentLink.click();
    await expect(page).toHaveURL(documentAddress(id, trip));
    await expect(docTabs.document(trip).show).toHaveAttribute('aria-selected', 'true');
    expect(await docTabs.keys()).toEqual([`document ${trip}`, `attachment ${notes}`]);

    // Its chip on the card opens the same tab, at the attachment's address under the item's.
    await docTabs.first.click();
    await timeline.item(trip).attachment(notes).click();
    await expect(page).toHaveURL(attachmentAddress(id, trip, notes));
    expect(await docTabs.keys()).toEqual([`document ${trip}`, `attachment ${notes}`]);
    await expect(overlay.documentLink).toBeVisible();

    // An item with no document names it, with no link.
    await docTabs.first.click();
    await timeline.item(notice).attachment(map).click();
    await expect(overlay.sub).toHaveText('Attachment of “The camp”');
    await expect(overlay.documentLink).toHaveCount(0);
  });

  test('the handbook opens as a tab of its own from the head’s button, and the project document from the Documents tab', async ({
    page,
    people,
    projects,
    projectHead,
    overlay,
    docTabs,
    panel,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Handbook'), members: [me.handle!] });
    await projects.saveProjectDocument(id, 'handbook', '---\ntitle: How we camp\n---\n\nWe leave no trace.\n');
    await timeline.open(id);

    await projectHead.handbookButton.click();
    await expect(page).toHaveURL(handbookAddress(id));
    await expect(docTabs.tab('handbook').title).toHaveText('How we camp');
    await expect(overlay.role).toHaveText('Handbook');

    await panel.documentsTab.click();
    await panel.projectDocument.root.click();
    await expect(page).toHaveURL(projectDocumentAddress(id));
    expect(await docTabs.keys()).toEqual(['handbook', 'project-document']);
    await expect(overlay.role).toHaveText('Project document');
  });

  test('the line scrolls where the tabs do not fit, the tab showing scrolled into it', async ({ people, projects, timeline, docTabs, panel }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Many'), members: [me.handle!] });
    const ids: string[] = [];
    for (let index = 0; index < 6; index++) {
      ids.push(await projects.place(id, { kind: 'document', title: `A document with a long title, number ${index + 1}`, text: card(`Doc ${index}`) }));
    }
    await timeline.open(id);
    await panel.documentsTab.click();
    for (const each of ids) await panel.document(each).root.click();
    const row = docTabs.root.locator('.doc-tabs-row');
    expect(await row.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
    const inRow = async (key: string) => {
      const [tab, line] = await Promise.all([docTabs.tab(key).root.boundingBox(), row.boundingBox()]);
      return tab!.x >= line!.x - 0.5 && tab!.x + tab!.width <= line!.x + line!.width + 0.5;
    };
    expect(await inRow(`document ${ids[5]}`)).toBe(true);
    // Each tab from 200 to 300px, its title cut short.
    for (const key of await docTabs.keys()) {
      const { width } = (await docTabs.tab(key).root.boundingBox())!;
      expect(width).toBeGreaterThanOrEqual(200);
      expect(width).toBeLessThanOrEqual(300);
    }
    expect(await inRow(`document ${ids[0]}`)).toBe(false);
    await panel.document(ids[0]).root.click();
    await expect.poll(() => inRow(`document ${ids[0]}`)).toBe(true);
    // Close all stays at the line's far right, outside the scrolling row.
    const [closeAll, line] = await Promise.all([docTabs.closeAll.boundingBox(), docTabs.root.boundingBox()]);
    expect(closeAll!.x + closeAll!.width).toBeLessThanOrEqual(line!.x + line!.width);
    expect(closeAll!.x).toBeGreaterThanOrEqual((await row.boundingBox())!.x + (await row.boundingBox())!.width);
  });

  test('a draft’s first tab is its definition chat; its material opens as a tab, and Discuss shows the chat again', async ({
    page,
    people,
    projects,
    overlay,
    docTabs,
    definitionChat,
    panel,
  }) => {
    const me = await people.signIn();
    const { id } = await projects.makeDraft({ members: [me.handle!] });
    const { ids } = await projects.attachToDraft(id, [NOTES]);
    await page.goto(`/projects/${id}`);
    await panel.documentsTab.click();
    await panel.attachment(ids[0]).root.click();

    await expect(docTabs.first).toHaveText('Chat');
    await expect(docTabs.attachment(ids[0]).title).toHaveText('Tent notes');
    await expect(overlay.sub).toHaveText('Attachment of the draft');
    await expect(definitionChat.root).toHaveAttribute('inert', '');

    await overlay.discuss.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(docTabs.first).toHaveAttribute('aria-selected', 'true');
    await expect(page).toHaveURL(`/projects/${id}`);
    await expect(definitionChat.quote).toBeVisible();
  });
});

test.describe('The focus and a tab', () => {
  test('a tab opened from the timeline takes the focus, Tab never reaches the timeline under it, and its cross gives the focus to the tab showing then', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    docTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Focus'), members: [me.handle!] });
    const notes = await projects.place(id, { kind: 'document', title: 'Packing notes', text: 'We leave on Friday.\n' });
    await projects.send(notes);
    await timeline.open(id);
    const { open } = timeline.item(notes);

    await open.focus();
    await page.keyboard.press('Enter');
    await expect(overlay.root).toBeFocused();
    await expect(overlay.root).toHaveAccessibleName(/Packing notes/);
    let inTab = 0;
    for (let step = 0; step < 16; step++) {
      await page.keyboard.press('Tab');
      expect(await timeline.root.evaluate((root) => root.contains(document.activeElement))).toBe(false);
      if (await overlay.root.evaluate((root) => root.contains(document.activeElement))) inTab++;
    }
    expect(inTab).toBeGreaterThan(0);

    await docTabs.document(notes).close.focus();
    await page.keyboard.press('Enter');
    await expect(overlay.root).toHaveCount(0);
    await expect(docTabs.root).toHaveCount(0);
    await expect(open).toBeFocused();
  });

  test('a tab shown from the line, or opened from the side panel, leaves the focus where it was; one closed by Done gives it back to what opened it', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    docTabs,
    panel,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Line focus'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: card('The trip') });
    await timeline.open(id);

    await timeline.item(trip).card.open.click();
    await docTabs.first.focus();
    await page.keyboard.press('Enter');
    await expect(overlay.root).toHaveCount(0);
    await expect(docTabs.first).toBeFocused();
    await docTabs.document(trip).show.focus();
    await page.keyboard.press('Enter');
    await expect(overlay.root).toBeVisible();
    await expect(docTabs.document(trip).show).toBeFocused();
    await docTabs.document(trip).close.click();

    await panel.documentsTab.click();
    const row = panel.document(trip).root;
    await row.focus();
    await page.keyboard.press('Enter');
    await expect(overlay.title).toHaveText('The trip');
    await expect(row).toBeFocused();
    await overlay.blockAt('D1').option('Dome').click();
    await overlay.blockAt('Q1').answerField.fill('By the lake');
    await overlay.blockAt('Q1').answerSend.click();
    await overlay.send.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(row).toBeFocused();
  });
});

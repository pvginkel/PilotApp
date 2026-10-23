/**
 * Attachments, reader's material (F17.5, F36): a chip each on every item the timeline draws that
 * carries one — a one-ask item, a notice, the opening, an inline document, a confirmation's card,
 * a document's card — and in the overlay's body; a done line's indicator, a document icon for the
 * one and a documents icon opening a menu of several (F13.6). Each opens in the overlay's
 * attachment view (F28.5), "Attachment of “<item>”" under its title, with an arrow back to the
 * document it was opened from; by its type a Markdown file read only, its fenced asks plain code,
 * an image inline, an SVG as an image that runs no script, plain text in a monospace block, and
 * anything else its title and size with Download, streamed.
 */

import { randomUUID } from 'node:crypto';
import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { documentAddress, documentAttachmentAddress } from '../support/page-objects/overlay-page';
import { attachmentAddress } from '../support/page-objects/timeline-page';
import type { AttachedFile } from '../support/projects';

const WORDS = (count: number) => Array.from({ length: count }, (_, index) => `word${index}`).join(' ');
const DECISION = 'Which tent for the trip?\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const QUESTION = 'Where do we pitch?\n\n```question id=Q1\n```\n';
const CONFIRMATION = 'The tag is cut.\n\n```decision id=C1\ntype: confirmation\nproposal: Push the release\nbecause: auto-pilot-off\n```\n';
const TENT = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const PITCH = '```question id=Q1\n```\n';
const SHORT = `We leave on Friday.\n\n## Which tent?\n\n${TENT}\n## Where do we pitch?\n\n${PITCH}`;
const SUMMARY = 'Where we go, what we take and who drives.';
const LONG = `---\nsummary: ${SUMMARY}\n---\n\n${WORDS(160)}\n\n## Which tent?\n\n${TENT}\n## Where do we pitch?\n\n${PITCH}`;

const NOTES: AttachedFile = {
  title: 'Tent notes',
  filename: 'tent-notes.md',
  content_type: 'text/markdown',
  content: '---\ntitle: Tent notes\nauthor: invented\n---\n# The tents we looked at\n\nThe dome is lighter.\n\n```decision id=D9\noptions:\n  - Dome\n```\n',
};
const file = (title: string): AttachedFile => ({
  title,
  filename: `${title.toLowerCase().replaceAll(' ', '-')}.md`,
  content_type: 'text/markdown',
  content: `# ${title}\n`,
});
const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
const SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"><script>window.svgRan = true</script>' +
  '<rect width="20" height="10" fill="teal"/></svg>';
const LOG = 'started\n  pitched the tent\nfinished\n';
// An HTML page is shown as no text: it downloads, 2048 bytes of it.
const PAGE = `<p>${'x'.repeat(2041)}</p>`;

test.describe('Attachments', () => {
  test('show a chip each on every item the timeline draws that carries one, the opening included, and none on an item without', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Attached'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    const notice = await projects.place(id, { kind: 'notice', title: 'The van is booked', text: 'Pick it up on Friday.\n' });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: CONFIRMATION });
    const inline = await projects.place(id, { kind: 'document', title: 'The short trip', text: SHORT });
    const card = await projects.place(id, { kind: 'document', title: 'The trip', text: LONG });
    const review = await projects.place(id, { kind: 'review', title: 'The plan', text: 'Read the plan through.\n' });
    const bare = await projects.place(id, { kind: 'notice', title: 'Nothing attached', text: 'Just words.\n' });
    const opening = (await projects.timeline(id)).items.find((item) => item.kind === 'opening')!.id;
    const attached = new Map<string, string>();
    for (const [index, item] of [opening, decision, notice, confirmation, inline, card, review].entries()) {
      const [attachment] = await projects.attach(item, [file(`Sketch ${index + 1}`)]);
      attached.set(item, attachment);
    }
    const [second] = await projects.attach(decision, [file('Second sketch')]);
    await timeline.open(id);

    await expect(timeline.openingAttachments).toHaveText(['Sketch 1']);
    await expect(timeline.openingAttachments).toHaveAttribute('data-attachment-id', attached.get(opening)!);
    for (const [index, item] of [decision, notice, confirmation, inline, card, review].entries()) {
      await expect(timeline.item(item).attachment(attached.get(item)!)).toHaveText(`Sketch ${index + 2}`);
    }
    await expect(timeline.item(decision).attachments).toHaveText(['Sketch 2', 'Second sketch']);
    await expect(timeline.item(decision).attachment(second)).toBeVisible();
    // On a card, between its progress and its actions, as the mockup's.
    for (const item of [card, review]) {
      const order = await timeline
        .item(item)
        .card.root.evaluate((root) => Array.from(root.children).map((child) => child.className || child.getAttribute('data-testid')));
      expect(order.indexOf('attachments')).toBe(order.indexOf('progress') + 1);
      expect(order.indexOf('item-actions')).toBe(order.indexOf('attachments') + 1);
    }
    await expect(timeline.item(bare).attachments).toHaveCount(0);
  });

  test('open from the timeline in the overlay’s attachment view, “Attachment of” its item with no way back; a Markdown file read only, its front matter left out, its fenced ask plain code; closing returns to the project', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Attached'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    const [notes] = await projects.attach(decision, [NOTES]);
    await timeline.open(id);

    await timeline.item(decision).attachment(notes).click();
    await expect(page).toHaveURL(attachmentAddress(id, decision, notes));
    await expect(overlay.title).toHaveText('Tent notes');
    await expect(overlay.sub).toHaveText('Attachment of “Which tent?”');
    await expect(overlay.back).toHaveCount(0);
    await expect(overlay.foot).toHaveCount(0);
    await expect(overlay.attachment.root).toHaveAttribute('data-view', 'markdown');
    await expect(overlay.attachment.prose.locator('h1')).toHaveText('The tents we looked at');
    await expect(overlay.attachment.prose).toContainText('The dome is lighter.');
    await expect(overlay.attachment.prose).not.toContainText('author: invented');
    await expect(overlay.attachment.prose.locator('pre code')).toHaveText('options:\n  - Dome\n');
    await expect(overlay.blocks).toHaveCount(0);
    // The timeline under it stays the item's, open.
    await expect(timeline.item(decision).block.root).toBeVisible();

    await overlay.close.click();
    await expect(page).toHaveURL(`/projects/${id}`);
    await expect(overlay.root).toHaveCount(0);
  });

  test('open from a document’s overlay in its place, the chips between the lead and the text, with an arrow back to it; Esc closes the overlay', async ({
    page,
    people,
    projects,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Attached'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: LONG });
    const [notes, map] = await projects.attach(trip, [NOTES, file('Route map')]);
    await overlay.open(id, trip);

    await expect(overlay.attachments).toHaveText(['Tent notes', 'Route map']);
    const order = await overlay.body
      .locator('.column')
      .evaluate((column) => Array.from(column.children).map((child) => child.getAttribute('data-testid') ?? child.className));
    expect(order.slice(0, 3)).toEqual(['overlay.summary', 'timeline.attachments', 'overlay.document']);

    await overlay.attachmentChip(map).click();
    await expect(page).toHaveURL(documentAttachmentAddress(id, trip, map));
    await expect(overlay.title).toHaveText('Route map');
    await expect(overlay.sub).toHaveText('Attachment of “The trip”');
    await expect(overlay.attachment.prose.locator('h1')).toHaveText('Route map');
    await expect(overlay.back).toBeVisible();
    await expect(overlay.back).toHaveText('');
    await expect(overlay.foot).toHaveCount(0);

    await overlay.back.click();
    await expect(page).toHaveURL(documentAddress(id, trip));
    await expect(overlay.title).toHaveText('The trip');
    await expect(overlay.summary).toHaveText(SUMMARY);
    await expect(overlay.back).toHaveCount(0);

    await overlay.attachmentChip(notes).click();
    await expect(overlay.title).toHaveText('Tent notes');
    await page.keyboard.press('Escape');
    await expect(page).toHaveURL(`/projects/${id}`);
    await expect(overlay.root).toHaveCount(0);
  });

  test('show an image inline from its stream, an SVG as an image that runs no script, and plain text in a monospace block', async ({
    page,
    people,
    projects,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Attached'), members: [me.handle!] });
    const notice = await projects.place(id, { kind: 'notice', title: 'The camp', text: 'What we saw.\n' });
    const [pixel, drawing, log] = await projects.attach(notice, [
      { title: 'Photo', filename: 'photo.png', content_type: 'image/png', content: PIXEL },
      { title: 'Drawing', filename: 'drawing.svg', content_type: 'image/svg+xml', content: SVG },
      { title: 'Log', filename: 'camp.log', content_type: 'text/plain; charset=utf-8', content: LOG },
    ]);

    await page.goto(attachmentAddress(id, notice, pixel));
    await expect(overlay.attachment.root).toHaveAttribute('data-view', 'image');
    await expect(overlay.attachment.image).toHaveAttribute('src', `/api/attachments/${pixel}`);
    await expect(overlay.attachment.image).toHaveAttribute('alt', 'Photo');
    await expect.poll(() => overlay.attachment.image.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBe(1);

    await page.goto(attachmentAddress(id, notice, drawing));
    await expect(overlay.attachment.root).toHaveAttribute('data-view', 'svg');
    await expect(overlay.attachment.image).toHaveAttribute('src', /^data:image\/svg\+xml;/);
    await expect.poll(() => overlay.attachment.image.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBe(20);
    expect(await page.evaluate(() => (window as Window & { svgRan?: boolean }).svgRan)).toBeUndefined();

    await page.goto(attachmentAddress(id, notice, log));
    await expect(overlay.attachment.root).toHaveAttribute('data-view', 'text');
    await expect(overlay.title).toHaveText('Log');
    await expect.poll(() => overlay.attachment.text.evaluate((text) => text.textContent)).toBe(LOG);
    expect(await overlay.attachment.text.evaluate((text) => getComputedStyle(text).fontFamily)).toContain('monospace');
  });

  test('show anything else as its title, its file’s name and size, and Download, which downloads it from its stream', async ({
    page,
    people,
    projects,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Attached'), members: [me.handle!] });
    const notice = await projects.place(id, { kind: 'notice', title: 'The camp', text: 'What we saw.\n' });
    const [site] = await projects.attach(notice, [{ title: 'Camp site', filename: 'site.html', content_type: 'text/html', content: PAGE }]);

    await page.goto(attachmentAddress(id, notice, site));
    await expect(overlay.attachment.root).toHaveAttribute('data-view', 'file');
    await expect(overlay.attachment.fileTitle).toHaveText('Camp site');
    await expect(overlay.attachment.size).toHaveText('site.html · 2 KB');
    await expect(overlay.attachment.prose).toHaveCount(0);

    // The download is the opener's, from the window it opens and closes.
    const downloaded = page.waitForEvent('download');
    await overlay.attachment.download.click();
    const download = await downloaded;
    expect(download.suggestedFilename()).toBe('site.html');
    expect(download.url()).toMatch(new RegExp(`/api/attachments/${site}$`));
  });

  test('carry a done line’s indicator: one attachment’s document icon opens it, several’s documents icon a menu of them', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Attached'), members: [me.handle!] });
    const one = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    const several = await projects.place(id, { kind: 'question', title: 'Where do we pitch?', text: QUESTION });
    const none = await projects.place(id, { kind: 'notice', title: 'Nothing attached', text: 'Just words.\n' });
    const [notes] = await projects.attach(one, [NOTES]);
    const [, map] = await projects.attach(several, [file('Lake map'), file('Route map')]);
    await projects.answer(one, 'D1', 'Dome');
    await projects.answer(several, 'Q1', 'By the lake');
    await timeline.open(id);
    await timeline.item(none).read.click();

    await expect(timeline.item(one).line).toBeVisible();
    await expect(timeline.item(one).attachments).toHaveCount(0);
    await expect(timeline.item(one).lineAttachments).toHaveCount(0);
    await expect(timeline.item(several).lineAttachment).toHaveCount(0);
    await expect(timeline.item(none).line).toBeVisible();
    await expect(timeline.item(none).lineAttachment).toHaveCount(0);
    await expect(timeline.item(none).lineAttachments).toHaveCount(0);

    await timeline.item(one).lineAttachment.click();
    await expect(page).toHaveURL(attachmentAddress(id, one, notes));
    await expect(overlay.title).toHaveText('Tent notes');
    await expect(overlay.sub).toHaveText('Attachment of “Which tent?”');
    await overlay.close.click();

    await timeline.item(several).lineAttachments.click();
    await expect(timeline.item(several).lineAttachmentItems).toHaveText(['Lake map', 'Route map']);
    await timeline.item(several).lineAttachmentItems.filter({ hasText: 'Route map' }).click();
    await expect(timeline.item(several).lineAttachmentsMenu).toHaveCount(0);
    await expect(page).toHaveURL(attachmentAddress(id, several, map));
    await expect(overlay.title).toHaveText('Route map');
    await expect(overlay.sub).toHaveText('Attachment of “Where do we pitch?”');
  });

  test('that an address names on no item of it read “The document did not load”', async ({ page, people, projects, overlay }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Attached'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: LONG });
    const notice = await projects.place(id, { kind: 'notice', title: 'The camp', text: 'What we saw.\n' });
    const [notes] = await projects.attach(trip, [NOTES]);

    await page.goto(attachmentAddress(id, notice, notes));
    await expect(overlay.failed).toHaveText('The document did not load.');
    await expect(overlay.attachment.root).toHaveCount(0);

    await page.goto(documentAttachmentAddress(id, trip, randomUUID()));
    await expect(overlay.failed).toHaveText('The document did not load.');
    await expect(overlay.back).toBeVisible();
    await overlay.back.click();
    await expect(overlay.title).toHaveText('The trip');
    await expect(overlay.attachments).toHaveText(['Tent notes']);
  });
});

test.describe('Attachments on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  const TITLE = 'Architecture decision record: an event-sourced timeline with append-only versions per turn';

  /** A part lies on the screen, its left edge to its right. */
  const onScreen = async (page: Page, part: Locator) => {
    const box = (await part.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  };
  /** A text cut short, or a pane that scrolls sideways. */
  const overflows = (part: Locator) => part.evaluate((element) => element.scrollWidth > element.clientWidth);

  /** A chip with a long title: on the screen, its clip at its start, the title cut short inside it. */
  const fits = async (page: Page, chip: Locator) => {
    await expect(chip).toHaveAttribute('title', TITLE);
    await onScreen(page, chip);
    const [box, clip] = [(await chip.boundingBox())!, (await chip.locator('.icon').boundingBox())!];
    expect(clip.x).toBeGreaterThanOrEqual(box.x);
    expect(await chip.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    expect(await overflows(chip.locator('.name'))).toBe(true);
  };

  test('cut a long title short inside its chip, on the timeline and in the overlay’s body, which do not scroll sideways', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Attached'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: LONG });
    const [onItem] = await projects.attach(decision, [file(TITLE)]);
    const [onTrip] = await projects.attach(trip, [file(TITLE)]);
    await timeline.open(id);

    await fits(page, timeline.item(decision).attachment(onItem));
    await fits(page, timeline.item(trip).attachment(onTrip));
    expect(await overflows(timeline.root)).toBe(false);

    await overlay.open(id, trip);
    await fits(page, overlay.attachmentChip(onTrip));
    expect(await overflows(overlay.body)).toBe(false);
  });

  test('keep a done line’s menu of attachments on the screen under its button, a long title cut short and every entry in sight', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Attached'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await projects.attach(decision, [file(TITLE), file('Short')]);
    await projects.answer(decision, 'D1', 'Dome');
    await timeline.open(id);

    const item = timeline.item(decision);
    await item.lineAttachments.click();
    await expect(item.lineAttachmentItems).toHaveText([TITLE, 'Short']);
    await onScreen(page, item.lineAttachmentsMenu);
    for (const entry of await item.lineAttachmentItems.all()) await onScreen(page, entry);
    const [long, short] = [item.lineAttachmentItems.first(), item.lineAttachmentItems.last()];
    await expect(long.locator('.name')).toHaveAttribute('title', TITLE);
    expect(await overflows(long.locator('.name'))).toBe(true);
    expect(await overflows(short.locator('.name'))).toBe(false);
    const button = (await item.lineAttachments.boundingBox())!;
    expect((await item.lineAttachmentsMenu.boundingBox())!.y).toBeGreaterThanOrEqual(button.y + button.height);
    expect(await overflows(timeline.root)).toBe(false);
  });
});

/**
 * The views on a phone (F98.4, F98.5): what opens from a tab — a document, an attachment, a
 * draft's material hung on nothing, the project document, the handbook, a work item's session log —
 * is a view pushed over it, the whole screen over the head and the tabs, with no animation; an
 * arrow back at the left of its head, where the head's drawer button stands, at the top however
 * tall its head, and no cross, maximize or backdrop. A view opened from a view lies on top of it,
 * an attachment's link to its document Back to it where it lies under it. Done in a document's
 * view closes it; Discuss in a view takes every view off and shows the Chat tab, the quote in its
 * composer, the session log's Discuss included. Back is the browser's: a view is an entry of its
 * own, and Back, the arrow or Esc takes it off and shows what lay under it, the tab it was opened
 * from; a reload keeps the tab and the views; a view's address reached cold lies over the
 * project's Timeline, so that Back lands there, at the project's id too, which gives way to its own
 * address. A view keeps its scroll while another lies over it,
 * so that Back from an attachment shows its document where it was read; one opened afresh, or
 * reloaded, starts at its top.
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { documentAddress, documentAttachmentAddress, handbookAddress, projectDocumentAddress } from '../support/page-objects/overlay-page';
import { sessionLogAddress } from '../support/page-objects/session-log-page';
import { addressOf } from '../support/page-objects/timeline-page';
import { projectAddress, type AttachedFile } from '../support/projects';

const SUMMARY = 'Where we go, what we take and who drives.';
const WORDS = Array.from({ length: 160 }, (_, index) => `word${index}`).join(' ');
// A document of two asks, long enough to stand on the timeline as a card, which opens it.
const TRIP = `---\nsummary: ${SUMMARY}\n---\n\n${WORDS}\n\n## Book the van\n\n\`\`\`action id=A1\n\`\`\`\n\n## Pack the stove\n\n\`\`\`action id=A2\n\`\`\`\n`;
const NOTES: AttachedFile = {
  title: 'Tent notes',
  filename: 'tent-notes.md',
  content_type: 'text/markdown',
  content: '# The tents we looked at\n\nThe dome is lighter.\n',
};
const LIST: AttachedFile = { title: 'Packing list', filename: 'packing-list.md', content_type: 'text/markdown', content: '# Packing list\n\nThe stove.\n' };

/** The view as it stands on the frame it shows on, read before the page paints once it is drawn. */
function viewAsDrawn(page: Page) {
  return page.evaluate(
    () =>
      new Promise<{ x: number; y: number; width: number; opacity: string; animation: string }>((resolve) => {
        const read = () => {
          const view = document.querySelector('[data-testid="overlay"]');
          if (view === null) return false;
          const { x, y, width } = view.getBoundingClientRect();
          const style = getComputedStyle(view);
          resolve({ x, y, width, opacity: style.opacity, animation: style.animationName });
          return true;
        };
        const observer = new MutationObserver(() => read() && observer.disconnect());
        observer.observe(document.body, { childList: true, subtree: true });
      }),
  );
}

test.describe('Views on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('a document opened from the Documents tab is a view over the head and the tabs, drawn at once in its place, its arrow back where the drawer’s button stands and at the top however tall its head, with no cross, maximize or backdrop; the arrow shows the Documents tab again, adding no entry', async ({
    page,
    people,
    projects,
    projectHead,
    shell,
    overlay,
    panel,
    phoneTabs,
  }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    const me = await people.signIn();
    // A name long enough that the line under the view's title wraps, the view's head taller than the project's.
    const id = await projects.makeWithSession({ name: makeUnique('A trip to the lake with the whole family and the dog'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await projectHead.open(id);
    await expect(projectHead.root).toBeVisible();
    const drawer = (await shell.drawerToggle.boundingBox())!;
    const [head, tabs] = [(await projectHead.root.boundingBox())!, (await phoneTabs.root.boundingBox())!];

    await phoneTabs.tab('documents').tap();
    // The tab under the view keeps its place: the same panel, never drawn again.
    await panel.root.evaluate((element) => element.setAttribute('data-kept', ''));
    const drawn = viewAsDrawn(page);
    await panel.document(trip).root.tap();
    await expect(page).toHaveURL(documentAddress(id, trip));
    await expect(overlay.title).toHaveText('The trip');
    expect(await drawn).toMatchObject({ x: 0, y: head.y, width: 390, opacity: '1', animation: 'none' });
    const view = (await overlay.root.boundingBox())!;
    expect(view).toMatchObject({ x: 0, y: head.y, width: 390 });
    expect(view.y + view.height).toBe(tabs.y + tabs.height);
    // Drawn once: the entry saying it is a view draws it no second time.
    await overlay.root.evaluate((element) => element.setAttribute('data-kept', ''));

    await expect(overlay.back).toBeVisible();
    const arrow = (await overlay.back.boundingBox())!;
    expect(arrow.x).toBeCloseTo(drawer.x, 0);
    expect(arrow.y).toBeCloseTo(drawer.y, 0);
    expect(arrow.width).toBe(drawer.width);
    expect(arrow.height).toBe(drawer.height);
    expect((await overlay.head.boundingBox())!.height).toBeGreaterThan(head.height);
    await expect(overlay.back).toHaveAccessibleName('Back');
    await expect(overlay.close).toHaveCount(0);
    await expect(overlay.maximize).toHaveCount(0);
    await expect(overlay.backdrop).toHaveCount(0);
    await expect(overlay.discuss).toBeVisible();
    await expect(overlay.root).toHaveAttribute('data-kept', '');

    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));
    await expect(phoneTabs.tab('documents')).toHaveAttribute('aria-selected', 'true');
    await expect(panel.document(trip).root).toBeVisible();
    await expect(panel.root).toHaveAttribute('data-kept', '');
    await page.goBack();
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(page).toHaveURL(projectAddress(id));
  });

  test('an attachment opened from its document’s view lies on top of it: its arrow, Back and Esc each show the document again, as its document’s link does; Done in the document’s view closes it', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Stacked'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    const [notes] = await projects.attach(trip, [NOTES]);
    await timeline.open(id);

    await timeline.item(trip).card.open.tap();
    await expect(page).toHaveURL(documentAddress(id, trip));
    await overlay.attachmentChip(notes).tap();
    await expect(page).toHaveURL(documentAttachmentAddress(id, trip, notes));
    await expect(overlay.title).toHaveText('Tent notes');
    await expect(overlay.sub).toHaveText('Attachment of “The trip”');
    await expect(overlay.back).toHaveCount(1);
    await expect(overlay.discuss).toBeVisible();

    // The document's link is Back to it: forward is the attachment again.
    await overlay.documentLink.tap();
    await expect(page).toHaveURL(documentAddress(id, trip));
    await expect(overlay.summary).toHaveText(SUMMARY);
    await page.goForward();
    await expect(overlay.title).toHaveText('Tent notes');
    await overlay.back.tap();
    await expect(overlay.summary).toHaveText(SUMMARY);
    await page.goForward();
    await expect(overlay.title).toHaveText('Tent notes');
    await page.goBack();
    await expect(overlay.summary).toHaveText(SUMMARY);
    await page.goForward();
    await expect(overlay.title).toHaveText('Tent notes');
    await page.keyboard.press('Escape');
    await expect(page).toHaveURL(documentAddress(id, trip));
    await page.keyboard.press('Escape');
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');

    // Done closes the document's view as Back does: forward is the view again.
    const sent = await projects.place(id, { kind: 'document', title: 'The van', text: TRIP });
    await timeline.item(sent).card.open.tap();
    await overlay.blockAt('A1').done.tap();
    await overlay.blockAt('A2').done.tap();
    await overlay.send.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));
    await expect(timeline.item(sent).root).toHaveAttribute('data-state', 'done');
    await page.goForward();
    await expect(page).toHaveURL(documentAddress(id, sent));
  });

  test('a view keeps its scroll while another lies over it: Back from an attachment shows its document where it was read; one opened afresh, or reloaded, starts at its top', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Scrolled'), members: [me.handle!] });
    const paragraphs = Array.from({ length: 60 }, (_, index) => `Paragraph ${index + 1} of the trip.`).join('\n\n');
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: `${TRIP}\n${paragraphs}\n` });
    const [notes] = await projects.attach(trip, [NOTES]);
    await timeline.open(id);
    // The chip stands under the summary: a click that scrolls it into view would move the document.
    const toNotes = () => overlay.attachmentChip(notes).dispatchEvent('click');
    const scrolledDown = async () => {
      await expect(overlay.document).toContainText('Paragraph 60 of the trip.');
      await overlay.body.evaluate((body) => body.scrollTo({ top: body.scrollHeight }));
      await expect.poll(() => overlay.scrollTop()).toBeGreaterThan(0);
      return overlay.scrollTop();
    };

    await timeline.item(trip).card.open.tap();
    const read = await scrolledDown();
    await toNotes();
    await expect(page).toHaveURL(documentAttachmentAddress(id, trip, notes));
    await expect(overlay.title).toHaveText('Tent notes');
    expect(await overlay.scrollTop()).toBe(0);
    await overlay.back.tap();
    await expect(page).toHaveURL(documentAddress(id, trip));
    await expect(overlay.summary).toHaveText(SUMMARY);
    await expect.poll(() => overlay.scrollTop()).toBe(read);
    // Forward is the attachment again, and Back the document where it was read.
    await page.goForward();
    await expect(overlay.title).toHaveText('Tent notes');
    await page.goBack();
    await expect(overlay.summary).toHaveText(SUMMARY);
    await expect.poll(() => overlay.scrollTop()).toBe(read);

    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);
    await timeline.item(trip).card.open.tap();
    await expect(overlay.document).toContainText('Paragraph 60 of the trip.');
    expect(await overlay.scrollTop()).toBe(0);

    await scrolledDown();
    await page.reload();
    await expect(overlay.document).toContainText('Paragraph 60 of the trip.');
    expect(await overlay.scrollTop()).toBe(0);
  });

  test('a view’s address reached cold lies over the Timeline, so that Back lands there; its attachment’s document link opens the document’s view, which lies under nothing', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const before = await projects.makeWithSession({ name: makeUnique('Before'), members: [me.handle!] });
    const id = await projects.makeWithSession({ name: makeUnique('Cold'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    const [notes] = await projects.attach(trip, [NOTES]);
    await timeline.open(before);

    await page.goto(documentAttachmentAddress(id, trip, notes));
    await expect(overlay.title).toHaveText('Tent notes');
    await overlay.documentLink.tap();
    await expect(page).toHaveURL(documentAddress(id, trip));
    await expect(overlay.summary).toHaveText(SUMMARY);
    await overlay.back.tap();
    await expect(page).toHaveURL(documentAttachmentAddress(id, trip, notes));
    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(timeline.root).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(projectAddress(before));
  });

  test('a view’s address reached cold at the project’s id gives way to the project’s own, still a view over the Timeline, so that Back lands there', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const before = await projects.makeWithSession({ name: makeUnique('Before'), members: [me.handle!] });
    const id = await projects.makeWithSession({ name: makeUnique('Cold'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await timeline.open(before);

    await page.goto(`/projects/${id}/documents/${trip}`);
    await expect(page).toHaveURL(documentAddress(id, trip));
    await expect(overlay.summary).toHaveText(SUMMARY);
    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(timeline.root).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(projectAddress(before));
  });

  test('a card’s document opened at one of its blocks lies under its attachment too: the attachment’s document link is Back to it, adding no entry', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('At a block'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    const [notes] = await projects.attach(trip, [NOTES]);
    await timeline.open(id);

    await page.goto(addressOf(id, trip, 'A2'));
    await expect(overlay.summary).toHaveText(SUMMARY);
    await overlay.attachmentChip(notes).tap();
    await expect(page).toHaveURL(documentAttachmentAddress(id, trip, notes));
    const entries = await page.evaluate(() => history.length);
    await overlay.documentLink.tap();
    await expect(page).toHaveURL(addressOf(id, trip, 'A2'));
    await expect(overlay.summary).toHaveText(SUMMARY);
    expect(await page.evaluate(() => history.length)).toBe(entries);
    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
  });

  test('a reload keeps the tab and the views, Back taking them off one by one down to the tab they were opened from', async ({
    page,
    people,
    projects,
    projectHead,
    overlay,
    panel,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Reload'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    const [notes] = await projects.attach(trip, [NOTES]);
    await projectHead.open(id);

    await phoneTabs.tab('documents').tap();
    await panel.document(trip).root.tap();
    await overlay.attachmentChip(notes).tap();
    await expect(overlay.title).toHaveText('Tent notes');
    await page.reload();
    await expect(overlay.title).toHaveText('Tent notes');
    await expect(page).toHaveURL(documentAttachmentAddress(id, trip, notes));

    await page.goBack();
    await expect(overlay.summary).toHaveText(SUMMARY);
    await page.goBack();
    await expect(overlay.root).toHaveCount(0);
    await expect(phoneTabs.tab('documents')).toHaveAttribute('aria-selected', 'true');
    await page.goBack();
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
  });

  test('Discuss in a view over a view takes every view off and shows the Chat tab, the quote in its composer; Back from it shows the Timeline', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    chat,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Discussed'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    const [notes] = await projects.attach(trip, [NOTES]);
    await timeline.open(id);

    await timeline.item(trip).card.open.tap();
    await overlay.attachmentChip(notes).tap();
    await expect(overlay.title).toHaveText('Tent notes');
    const quote = await overlay.discuss.getAttribute('data-quote');
    await overlay.discuss.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(phoneTabs.tab('chat')).toHaveAttribute('aria-selected', 'true');
    await expect(chat.quote).toHaveAttribute('data-quote', quote!);
    await expect(page).toHaveURL(projectAddress(id));

    await page.goBack();
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(overlay.root).toHaveCount(0);
  });

  test('a work item’s session log is a view over the Timeline, keeping its Discuss, which shows the Chat tab with the item quoted', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    sessionLog,
    chat,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Logged'), members: [me.handle!] });
    const work = await projects.startWork(id, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await timeline.open(id);

    await timeline.item(work).work.sessionLog.tap();
    await expect(page).toHaveURL(sessionLogAddress(id, work));
    await expect(sessionLog.title).toHaveText('Session log');
    await expect(overlay.back).toBeVisible();
    await expect(overlay.close).toHaveCount(0);
    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await page.goForward();

    await sessionLog.discuss.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(phoneTabs.tab('chat')).toHaveAttribute('aria-selected', 'true');
    await expect(chat.quote).toHaveAttribute('data-quote', `item ${work}`);
  });

  test('the Documents tab’s project document and handbook rows open as views over it, the arrow back showing the tab', async ({
    page,
    people,
    projects,
    projectHead,
    overlay,
    panel,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Rows'), members: [me.handle!] });
    await projects.saveProjectDocument(id, 'handbook', '# How we travel\n\nHow the trip is planned.\n');
    await projectHead.open(id);

    await phoneTabs.tab('documents').tap();
    await panel.projectDocument.root.tap();
    await expect(page).toHaveURL(projectDocumentAddress(id));
    await expect(overlay.role).toHaveText('Project document');
    await overlay.back.tap();
    await expect(phoneTabs.tab('documents')).toHaveAttribute('aria-selected', 'true');

    await panel.handbook.root.tap();
    await expect(page).toHaveURL(handbookAddress(id));
    await expect(overlay.title).toHaveText('How we travel');
    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(phoneTabs.tab('documents')).toHaveAttribute('aria-selected', 'true');
  });

  test('a draft’s material hung on nothing opens from its Documents tab as a view over it', async ({ page, people, projects, projectHead, overlay, panel, phoneTabs }) => {
    const me = await people.signIn();
    const { id } = await projects.makeDraft({ members: [me.handle!] });
    const {
      ids: [list],
    } = await projects.attachToDraft(id, [LIST]);
    await projectHead.open(id);

    await phoneTabs.tab('documents').tap();
    await panel.attachment(list).root.tap();
    await expect(overlay.title).toHaveText('Packing list');
    await expect(overlay.sub).toHaveText('Attachment of the draft');
    await expect(overlay.back).toBeVisible();
    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(phoneTabs.tab('documents')).toHaveAttribute('aria-selected', 'true');
    await expect(page).toHaveURL(projectAddress(id));
  });
});

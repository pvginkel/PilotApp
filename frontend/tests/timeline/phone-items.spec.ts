/**
 * An item on a phone (F99, F13.9). Its address shows the item alone, full screen, as a view pushed
 * over the tabs (F98.4): the item as the timeline draws it, its option rows a thumb's height and
 * Other's console kept above the keyboard while it is typed in, answered in place as there; a
 * notification's link reached cold lies over the project's Timeline, and an item no longer open
 * shows as it stands. A block's address shows its item alone at the block, or a card's document
 * at it; a quote's chip and a claimed action's link push the item alone over the tab they stand
 * on. A done line shows Undo alone among its actions, and a tap on it opens its view, whose head
 * carries Discuss; Undo undoes and opens nothing. Off a phone the line and the address are as they
 * were.
 */

import { randomUUID } from 'node:crypto';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { documentAddress } from '../support/page-objects/overlay-page';
import { sessionLogAddress } from '../support/page-objects/session-log-page';
import { addressOf, attachmentAddress } from '../support/page-objects/timeline-page';

const SHELTERS = ['Dome', 'Tunnel', 'Tarp', 'Hammock', 'Bivvy', 'Cabin'];
const DECISION = `Which shelter do we take?\n\n\`\`\`decision id=D1\noptions:\n${SHELTERS.map((shelter) => `  - ${shelter}`).join('\n')}\n\`\`\`\n`;
const WORDS = Array.from({ length: 160 }, (_, index) => `word${index}`).join(' ');
// A document of two asks, long enough to stand on the timeline as a card.
const TRIP = `---\nsummary: Where we go.\n---\n\n${WORDS}\n\n## Book the van\n\n\`\`\`action id=A1\n\`\`\`\n\n## Pack the stove\n\n\`\`\`action id=A2\n\`\`\`\n`;
const AT = 'at: 2026-10-20T09:00:00Z';
const STOPS = Array.from({ length: 30 }, (_, index) => `Stop ${index + 1}.`).join('\n\n');
// A short document of three asks, drawn inline: two sections Pilot settled, each folded to its line, the last far below the view's fold.
const ROUTE = [
  '## Which tent?\n',
  `\`\`\`decision id=D1\noptions:\n  - Dome\n  - Tunnel\nanswer: Dome\nby: agent\n${AT}\n\`\`\`\n`,
  '## Book the van\n',
  '```action id=A1\n```\n',
  `${STOPS}\n`,
  '## Where do we pitch?\n',
  `\`\`\`question id=Q1\nanswer: Lake Garda\nby: agent\n${AT}\n\`\`\`\n`,
].join('\n');
const ROTATING = 'Rotating the CI token';
const CUT_OVER_PATH = '/work/Example/cut-over.md';
const CUT_OVER = '# The cut-over\n\n```action id=A1\nanswer: Pilot does it\nby: agent\nat: 2026-10-20T09:00:00Z\n```\n\n```decision id=D1\noptions:\n  - Friday\n  - Monday\n```\n';
const PHONE = { width: 390, height: 844 };

test.describe('The item alone on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('a notification’s link reached cold shows the item alone over the whole screen, under the project’s name, its option rows a thumb’s height; Back lands on the project’s Timeline', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    projectHead,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const before = await projects.makeWithSession({ name: makeUnique('Before'), members: [me.handle!] });
    const name = makeUnique('Shelter');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which shelter?', text: DECISION });
    await timeline.open(before);

    await timeline.openAt(id, decision);
    const alone = timeline.item(decision, overlay.alone);
    await expect(alone.root).toHaveAttribute('data-state', 'open');
    await expect(alone.title).toHaveText('Which shelter?');
    await expect(overlay.title).toHaveText(name);
    await expect(overlay.back).toBeVisible();
    await expect(overlay.close).toHaveCount(0);
    const [view, head, tabs] = await Promise.all([overlay.root, projectHead.root, phoneTabs.root].map(async (each) => (await each.boundingBox())!));
    expect(view).toMatchObject({ x: 0, y: head.y, width: PHONE.width });
    expect(view.y + view.height).toBe(tabs.y + tabs.height);
    await expect(alone.block.options).toHaveCount(SHELTERS.length);
    for (const row of [...(await alone.block.options.all()), alone.block.other]) {
      expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(48);
    }

    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${id}`);
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(timeline.item(decision).root).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(`/projects/${before}`);
  });

  test('answered, the item alone answers as the timeline’s does, and opened again it shows as it stands, its line opening its document over it', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Answered'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which shelter?', text: DECISION });
    await timeline.openAt(id, decision);
    const alone = timeline.item(decision, overlay.alone);

    await alone.block.option('Tunnel').tap();
    await expect(alone.root).toHaveAttribute('data-state', 'done');
    await expect(alone.said).toHaveText('Tunnel');
    await expect(alone.undo).toBeVisible();

    await page.reload();
    await expect(alone.lineTitle).toHaveText('Which shelter?');
    await alone.lineTitle.tap();
    await expect(page).toHaveURL(documentAddress(id, decision));
    await expect(overlay.discuss).toBeVisible();
    await overlay.back.tap();
    await expect(page).toHaveURL(addressOf(id, decision));
    await expect(alone.said).toHaveText('Tunnel');
  });

  test('Other’s console stays above the keyboard while it is typed in, and sends the words as the answer', async ({ page, people, projects, timeline, overlay }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Other'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which shelter?', text: DECISION });
    await timeline.openAt(id, decision);
    const alone = timeline.item(decision, overlay.alone);

    await alone.block.other.tap();
    await expect(alone.block.field).toBeFocused();
    // The keyboard opening: the page's viewport resizes its content to what the keyboard leaves.
    await page.setViewportSize({ width: PHONE.width, height: 300 });
    await expect(alone.block.console).toBeInViewport({ ratio: 1 });

    await alone.block.field.fill('A tent from the neighbours');
    await alone.block.send.tap();
    await expect(alone.root).toHaveAttribute('data-state', 'done');
    await expect(alone.said).toHaveText('A tent from the neighbours');
  });

  test('a block’s address shows its item alone at the block, a card’s its document at it; an address naming no item says the item did not load', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Blocks'), members: [me.handle!] });
    const route = await projects.place(id, { kind: 'document', title: 'The route', text: ROUTE });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });

    // Its folded section opens, the view scrolled down to the block, which flashes; the other stays its line.
    await timeline.openAt(id, route, 'Q1');
    const alone = timeline.item(route, overlay.alone);
    const pitch = alone.blockAt('Q1');
    await expect(pitch.root).toHaveClass(/\bflash\b/);
    await expect(pitch.root).toBeInViewport();
    expect(await overlay.scrollTop()).toBeGreaterThan(0);
    await expect(alone.settledLine('Q1').root).toHaveCount(0);
    await expect(alone.settledLine('D1').root).toHaveCount(1);

    await page.goto(addressOf(id, trip, 'A1'));
    await expect(overlay.document).toBeVisible();
    await expect(overlay.alone).toHaveCount(0);
    await expect(overlay.blockAt('A1').root).toBeInViewport();

    await page.goto(addressOf(id, randomUUID()));
    await expect(overlay.failed).toHaveText('The item did not load.');
  });

  test('a quote’s chip going to an item pushes it alone over the Chat tab, which Back shows again', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    chat,
    chats,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Quoted'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which shelter?', text: DECISION });
    await chats.start(id, `<quoted_item id="${decision}">Which shelter?</quoted_item id="${decision}"> Still open?`);
    await timeline.open(id);

    await phoneTabs.tab('chat').tap();
    await chat.quotes.first().tap();
    await expect(page).toHaveURL(addressOf(id, decision));
    await expect(timeline.item(decision, overlay.alone).root).toBeVisible();
    await page.goBack();
    await expect(overlay.root).toHaveCount(0);
    await expect(phoneTabs.tab('chat')).toHaveAttribute('aria-selected', 'true');
  });

  test('a claimed action’s link pushes the work item that does it alone over the Timeline', async ({
    page,
    people,
    projects,
    controller,
    chats,
    timeline,
    overlay,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Claimed'), members: [me.handle!] });
    const work = await projects.startWork(id, { title: 'Planning the cut-over', brief: 'Plan the cut-over.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(id, work)).state).toBe('running');
    const { id: environment } = await projects.environment(id, work);
    await controller.putFile(environment, CUT_OVER_PATH, CUT_OVER);
    const document = await projects.register(work, CUT_OVER_PATH);
    const passed = await chats.passing(id);
    await controller.finish(environment, 'claude-1');
    await expect.poll(async () => (await projects.item(id, document)).awaiting_read).toBe(false);
    await passed();
    const rotating = await projects.startWork(id, { title: ROTATING, brief: 'Rotate the CI token.', cwd: '/work/Example', claims: [`${document}/A1`] });
    await timeline.open(id);

    await timeline.item(document).blockAt('A1').held.pilots.tap();
    await expect(page).toHaveURL(addressOf(id, rotating));
    await expect(timeline.item(rotating, overlay.alone).root).toBeVisible();
    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(page).toHaveURL(`/projects/${id}`);
  });
});

test.describe('A done line on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('shows Undo alone among its actions, its attachment, time and answer staying; a tap on it opens its document as a view with Discuss, on its attachment the attachment, and on Undo undoes, opening nothing', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Lines'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which shelter?', text: DECISION });
    const [notes] = await projects.attach(decision, [
      { title: 'Shelter notes', filename: 'shelter-notes.md', content_type: 'text/markdown', content: '# Shelters\n' },
    ]);
    await projects.answer(decision, 'D1', 'Tunnel');
    await timeline.open(id);
    const item = timeline.item(decision);

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineKind).toBeVisible();
    await expect(item.lineTitle).toHaveText('Which shelter?');
    await expect(item.lineTime).toBeVisible();
    await expect(item.said).toHaveText('Tunnel');
    await expect(item.lineAttachment).toBeVisible();
    await expect(item.undo).toBeVisible();
    await expect(item.open).toHaveCount(0);
    await expect(item.lineDiscuss).toHaveCount(0);

    await item.said.tap();
    await expect(page).toHaveURL(documentAddress(id, decision));
    await expect(overlay.discuss).toBeVisible();
    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);

    await item.lineAttachment.tap();
    await expect(page).toHaveURL(attachmentAddress(id, decision, notes));
    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);

    await item.undo.tap();
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${id}`);
  });

  test('a work item’s opens its session log as a view, whose head carries Discuss', async ({ page, people, projects, timeline, sessionLog }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Logged'), members: [me.handle!] });
    const work = await projects.startWork(id, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await projects.transition(id, 'finished');
    await timeline.open(id);
    const item = timeline.item(work);

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.open).toHaveCount(0);
    await item.lineTitle.tap();
    await expect(page).toHaveURL(sessionLogAddress(id, work));
    await expect(sessionLog.discuss).toBeVisible();
  });
});

test.describe('Off a phone', () => {
  test('a done line keeps Open and Discuss, and a click on it opens nothing; an item’s address goes to the item in the timeline', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Desk'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which shelter?', text: DECISION });
    await projects.answer(decision, 'D1', 'Tunnel');
    await timeline.openAt(id, decision);
    const item = timeline.item(decision);

    await expect(overlay.root).toHaveCount(0);
    await expect(item.root).toBeInViewport();
    await expect(item.open).toBeVisible();
    await expect(item.lineDiscuss).toBeVisible();
    await item.lineTitle.click();
    await expect(page).toHaveURL(addressOf(id, decision));
    await expect(overlay.root).toHaveCount(0);
  });
});

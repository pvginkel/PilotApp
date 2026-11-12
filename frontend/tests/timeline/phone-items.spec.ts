/**
 * An item on a phone (F99, F13.9). Its address shows the item alone, full screen, as a view pushed
 * over the tabs (F98.4): the item as the timeline draws it, under the project's name and its plan
 * step, at most two lines, its option rows a thumb's height and
 * Other's console kept above the keyboard while it is typed in, answered in place as there; a
 * notification's link reached cold lies over the project's Timeline, and an item no longer open
 * shows as it stands. A block's address shows its item alone at the block, or a card's document
 * at it; a quote's chip and a claimed action's link push the item alone over the tab they stand
 * on. A done line shows Undo alone among its actions, and a tap on it opens its view, whose head
 * carries Discuss, its title the way in from the keyboard; Undo undoes and opens nothing. An item's
 * head keeps Discuss at the end of its first line however the rest wraps, and puts "for <user>" on a
 * line of its own under the rest, led by its icon, on every kind; no row of it ends on a dot, each
 * dot going with the part after it, a part wider than the row wrapping behind its dot; and Urgent's
 * triangle stands centred on the capitals of the head's text, as the kind's icon. Off a phone the
 * line keeps its actions under the mouse, and the address is as it was.
 */

import { randomUUID } from 'node:crypto';
import type { Locator } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique, makeUniqueToken } from '../support/helpers';
import { documentAddress } from '../support/page-objects/overlay-page';
import { sessionLogAddress } from '../support/page-objects/session-log-page';
import { addressOf, attachmentAddress, dotsEndingARow, type TimelinePage } from '../support/page-objects/timeline-page';
import type { People } from '../support/people';
import { projectAddress, type Projects } from '../support/projects';
import type { Waits } from '../support/waits';
import type { components } from '@/lib/api/generated/types';

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

type ItemKind = components['schemas']['InventedItemCreateSchema.6d6b324']['kind'];
const box = async (locator: Locator) => (await locator.boundingBox())!;

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
    await expect(page).toHaveURL(projectAddress(id));
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(timeline.item(decision).root).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(projectAddress(before));
  });

  test('the item alone cuts a long plan step under the project’s name at two lines, ellipsized, its whole title its tooltip', async ({
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const step = `Pitch the shelter ${Array.from({ length: 22 }, (_, index) => `wordwordword${index}`).join(' ')}`;
    const name = makeUnique('Long step');
    const id = await projects.makeWithSession({ name, members: [me.handle!], tasks: [{ id: 'pitch', title: step, status: 'in_progress' }] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which shelter?', text: `---\nstep: pitch\n---\n\n${DECISION}` });
    await timeline.openAt(id, decision);

    await expect(timeline.item(decision, overlay.alone).root).toBeVisible();
    await expect(overlay.title).toHaveText(name);
    await expect(overlay.step).toHaveText(step);
    await expect(overlay.step).toHaveAttribute('title', step);
    const shown = await overlay.step.evaluate((element) => ({
      lines: Math.round(element.clientHeight / parseFloat(getComputedStyle(element).lineHeight)),
      cut: element.scrollHeight > element.clientHeight,
      // In the face and the size of the head's line under the name.
      plain: (['fontFamily', 'fontSize'] as const).every((face) => getComputedStyle(element)[face] === getComputedStyle(element.parentElement!)[face]),
      body: getComputedStyle(element).fontFamily === getComputedStyle(document.body).fontFamily,
    }));
    expect(shown).toEqual({ lines: 2, cut: true, plain: true, body: true });
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
    await expect(page).toHaveURL(projectAddress(id));
  });
});

test.describe('An item’s head on a phone', () => {
  test.use({ viewport: PHONE });

  /** Discuss stands at the end of the head's first line, the line the kind's on. */
  const discussOnFirstLine = async (head: Locator, kind: Locator, discuss: Locator) => {
    const [headBox, kindBox, discussBox] = await Promise.all([box(head), box(kind), box(discuss)]);
    expect(discussBox.y).toBeCloseTo(headBox.y, 0);
    expect(discussBox.x + discussBox.width).toBeCloseTo(headBox.x + headBox.width, 0);
    expect(Math.abs(discussBox.y + discussBox.height / 2 - (kindBox.y + kindBox.height / 2))).toBeLessThan(2);
  };

  /**
   * A project with an urgent item of every kind for Ben, the confirmation's reason long enough that
   * its head wraps before it, and a wait, opened; answers the items' ids in their order, and the
   * wait's.
   */
  const everyKind = async (people: People, projects: Projects, waits: Waits, timeline: TimelinePage): Promise<{ placed: string[]; wait: string }> => {
    const ben = makeUnique('ben', 8);
    await people.other(ben, 'Ben Example');
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Heads'), members: [me.handle!, ben] });
    const front = `---\nfor: ${ben}\nurgent: true\n---\n\n`;
    const cases: [ItemKind, string][] = [
      ['decision', `${front}\`\`\`decision id=D1\noptions:\n  - Dome\n  - Tunnel\n\`\`\`\n`],
      // A reason long enough that the head wraps before it.
      ['confirmation', `${front}\`\`\`decision id=C1\ntype: confirmation\nproposal: Grant the deploy key\nbecause: standing-grant\n\`\`\`\n`],
      ['question', `${front}\`\`\`question id=Q1\n\`\`\`\n`],
      ['action', `${front}Plug it in.\n\n\`\`\`action id=A1\n\`\`\`\n`],
      ['notice', `${front}Blue and green.\n`],
      ['review', `${front}Read it through.\n`],
      ['document', `${front}The camp, in two asks.\n\n\`\`\`action id=A1\n\`\`\`\n\n\`\`\`action id=A2\n\`\`\`\n`],
      // Long enough to leave a card.
      ['document', TRIP.replace('---\n', `---\nfor: ${ben}\nurgent: true\n`)],
    ];
    const placed: string[] = [];
    for (const [kind, text] of cases) placed.push(await projects.place(id, { kind, title: `A ${kind} for Ben`, text }));
    const key = `H${makeUniqueToken(6).toUpperCase()}`;
    const wait = await waits.add(id, { kind: 'card_wait', title: 'The night shift takes the cards', cards: [`${key}-1`], states: ['Done'] });
    await timeline.open(id);
    return { placed, wait };
  };

  test('puts “for <user>” on a line of its own under the rest, led by its icon, and keeps Discuss at the end of its first line however the rest wraps, on every kind', async ({
    people,
    projects,
    waits,
    timeline,
  }) => {
    const { placed, wait } = await everyKind(people, projects, waits, timeline);

    for (const each of placed) {
      const item = timeline.item(each);
      await expect(item.forUser).toHaveText('for Ben Example');
      await expect(item.forUser.locator('svg')).toBeVisible();
      await expect(item.urgent).toBeVisible();
      const [head, kind, chip] = await Promise.all([box(item.head), box(item.kind), box(item.forUser)]);
      expect(chip.y).toBeGreaterThanOrEqual(kind.y + kind.height);
      expect(chip.x).toBeCloseTo(head.x, 0);
      await discussOnFirstLine(item.head, item.kind, item.discuss);
    }
    const confirmation = timeline.item(placed[1]);
    const [kind, why] = await Promise.all([box(confirmation.kind), box(confirmation.why)]);
    expect(why.y).toBeGreaterThanOrEqual(kind.y + kind.height);

    // A wait's request still touches Discuss.
    const item = timeline.item(wait);
    await expect(item.forUser).toHaveCount(0);
    await discussOnFirstLine(item.head, item.kind, item.discuss);
    const [request, discuss] = await Promise.all([box(item.wait.request), box(item.discuss)]);
    expect(request.x + request.width).toBeCloseTo(discuss.x, 0);
  });

  test('ends no row on a dot, each dot going with the part after it, a reason wider than the row wrapping behind its dot, on every kind', async ({
    page,
    people,
    projects,
    waits,
    timeline,
  }) => {
    const { placed, wait } = await everyKind(people, projects, waits, timeline);
    const confirmation = timeline.item(placed[1]);
    const dot = confirmation.head.locator('.sep').last();
    const rows = async () => {
      const [kind, at, why] = await Promise.all([box(confirmation.kind), box(dot), box(confirmation.why)]);
      return { kind, at, why };
    };

    for (const each of [...placed, wait]) expect(await dotsEndingARow(timeline.item(each).head)).toBe(0);
    // The reason starts the head's second row behind its dot, on one line.
    const wide = await rows();
    expect(wide.at.y).toBeGreaterThanOrEqual(wide.kind.y + wide.kind.height - 1);
    expect(wide.why.x).toBeGreaterThan(wide.at.x + wide.at.width);
    expect(wide.why.height).toBeCloseTo(wide.at.height, 0);

    // On the narrowest phone the reason is wider than the row: it wraps behind its dot, inside the card.
    await page.setViewportSize({ width: 280, height: 653 });
    await expect.poll(async () => (await rows()).why.height).toBeGreaterThan(wide.why.height + 20);
    for (const each of [...placed, wait]) {
      const item = timeline.item(each);
      expect(await dotsEndingARow(item.head)).toBe(0);
      expect(await item.head.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(0);
    }
    const narrow = await rows();
    expect(narrow.why.y).toBeCloseTo(narrow.at.y, 0);
    expect(narrow.why.x).toBeGreaterThan(narrow.at.x + narrow.at.width);
  });

  test('stands Urgent’s triangle centred on the capitals of the head’s text, as the kind’s icon, at its chip’s size, on every kind', async ({
    people,
    projects,
    waits,
    timeline,
  }) => {
    const { placed } = await everyKind(people, projects, waits, timeline);

    for (const each of placed) {
      const item = timeline.item(each);
      await expect(item.urgent).toBeVisible();
      const [kind, triangle] = await Promise.all([box(item.kind.locator('.icon')), box(item.urgent.locator('.icon'))]);
      // Level with the kind's icon, a whole number of the head's 28 px rows under it where the head wraps.
      const under = triangle.y + triangle.height / 2 - (kind.y + kind.height / 2);
      expect(Math.abs(under - 28 * Math.round(under / 28))).toBeLessThan(0.1);
      expect(triangle.height).toBe(13);
      expect(triangle.width).toBe(13);
    }
  });

  test('of a work item keeps Discuss at the end of its first line, Session log and Stop beside it', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Work head'), members: [me.handle!] });
    const work = await projects.startWork(id, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(id, work)).state).toBe('running');
    await timeline.open(id);
    const item = timeline.item(work);

    await expect(item.work.running).toBeVisible();
    await discussOnFirstLine(item.head, item.kind, item.discuss);
    const [log, stop, discuss] = await Promise.all([box(item.work.sessionLog), box(item.work.stop), box(item.discuss)]);
    expect(stop.y).toBeCloseTo(discuss.y, 0);
    expect(log.y).toBeCloseTo(discuss.y, 0);
    expect(discuss.x - (stop.x + stop.width)).toBeCloseTo(4, 0);
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
    await expect(page).toHaveURL(projectAddress(id));
  });

  test('has its title as its way in from the keyboard and a screen reader, a link named by the title that opens its document’s view; a work item’s its session log’s', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    sessionLog,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Keys'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which shelter?', text: DECISION });
    const work = await projects.startWork(id, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await projects.answer(decision, 'D1', 'Tunnel');
    await projects.transition(id, 'finished');
    await timeline.open(id);
    const item = timeline.item(decision);

    const link = item.line.getByRole('link', { name: 'Which shelter?' });
    await expect(link).toHaveAttribute('href', documentAddress(id, decision));
    await item.lineTitle.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(documentAddress(id, decision));
    await expect(overlay.discuss).toBeVisible();
    await overlay.back.tap();
    await expect(overlay.root).toHaveCount(0);

    const line = timeline.item(work);
    await expect(line.root).toHaveAttribute('data-state', 'done');
    await expect(line.line.getByRole('link', { name: 'Surveying the stylesheets' })).toHaveAttribute('href', sessionLogAddress(id, work));
    await line.lineTitle.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(sessionLogAddress(id, work));
    await expect(sessionLog.discuss).toBeVisible();
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
  test('a done line keeps Open and Discuss under the mouse, and a click on it off its title opens nothing; an item’s address goes to the item in the timeline', async ({
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
    await item.line.hover();
    await expect(item.open).toBeVisible();
    await expect(item.lineDiscuss).toBeVisible();
    await item.said.click();
    await expect(page).toHaveURL(addressOf(id, decision));
    await expect(overlay.root).toHaveCount(0);
  });
});

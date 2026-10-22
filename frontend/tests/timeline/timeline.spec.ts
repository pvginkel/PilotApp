/**
 * A project's timeline (F8): its items in their order under their date and step dividers (F9); the
 * opening (F18.1, F18.2); an item's head (F12, F10.1, F107, F114); its prose as GFM, linked, folding
 * when long (F29.1, F12.2); a concept (F78); the done line (F13.1, F13.2); anchored to its end, a
 * new item flashing, and at its end on each project (F8.2, F1.6); "Nothing yet" (F113).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { Projects } from '../support/projects';
import type { components } from '@/lib/api/generated/types';

type TimelineItem = components['schemas']['TimelineSchema.1fdd8ae.TimelineItemSchema'];
type ItemKind = components['schemas']['InventedItemCreateSchema.6d6b324']['kind'];

// The browser's time zone, which every time on the timeline is shown in.
const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });

const format = (options: Intl.DateTimeFormatOptions) => {
  const formatter = new Intl.DateTimeFormat('en-GB', { ...options, timeZone: ZONE });
  return (at: string) => formatter.format(new Date(at));
};
const clock = format({ hour: '2-digit', minute: '2-digit' });
const day = format({ weekday: 'long', day: 'numeric', month: 'long' });
const stamp = format({ dateStyle: 'full', timeStyle: 'long' });

const DECISION = '```decision id=D1\noptions:\n  - Dome: up in five minutes\n  - Tunnel\n```\n';
const CONFIRMATION = '```decision id=C1\ntype: confirmation\nproposal: Push the release\nbecause: auto-pilot-off\n```\n';
const QUESTION = '```question id=Q1\n```\n';
const ACTION = 'Plug it in.\n\n```action id=A1\n```\n';
const DOCUMENT = [
  'The camp, in three asks.',
  '```action id=A1\n```',
  '```action id=A2\n```',
  '```decision id=D1\nproposal: Take the dome\n```',
].join('\n\n');

/** A day divider wherever the day changes, from what the API says the items were placed. */
function days(items: TimelineItem[]): string[] {
  return items.map((item) => day(item.created_at)).filter((label, index, labels) => label !== labels[index - 1]);
}

test.describe('The rows', () => {
  test('are the items in their order, the opening first, under a divider for the day they were placed', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Order'), members: [me.handle!] });
    await projects.place(id, { kind: 'notice', title: 'First notice', text: 'One.\n' });
    await projects.place(id, { kind: 'question', title: 'Second ask', text: QUESTION });
    await timeline.open(id);

    const { items } = await projects.timeline(id);
    const rows = await timeline.rowsRead();
    expect(rows.filter(([kind]) => kind === 'timeline.divider.day').map(([, text]) => text)).toEqual(days(items));
    expect(rows.filter(([kind]) => kind !== 'timeline.divider.day')).toEqual([
      ['timeline.opening', expect.stringContaining('You started this project')],
      ['timeline.item', expect.stringContaining('First notice')],
      ['timeline.item', expect.stringContaining('Second ask')],
    ]);
    expect(rows[0][0]).toBe('timeline.divider.day');
  });

  test('start a step divider where the step changes, titled by the plan; an item serving none starts none', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({
      name: makeUnique('Steps'),
      members: [me.handle!],
      tasks: [
        { id: 'build', title: 'Build the card', status: 'in_progress' },
        { id: 'ship', title: 'Ship it', status: 'pending' },
      ],
    });
    await projects.place(id, { kind: 'notice', title: 'Built one', text: '---\nstep: build\n---\n\nOne.\n' });
    await projects.place(id, { kind: 'notice', title: 'Aside', text: 'Two.\n' });
    await projects.place(id, { kind: 'notice', title: 'Built two', text: '---\nstep: build\n---\n\nThree.\n' });
    await projects.place(id, { kind: 'notice', title: 'Shipped', text: '---\nstep: ship\n---\n\nFour.\n' });
    await timeline.open(id);

    const rows = (await timeline.rowsRead()).filter(([kind]) => kind !== 'timeline.divider.day' && kind !== 'timeline.opening');
    expect(rows).toEqual([
      ['timeline.divider.step', 'Build the card'],
      ['timeline.item', expect.stringContaining('Built one')],
      ['timeline.item', expect.stringContaining('Aside')],
      ['timeline.item', expect.stringContaining('Built two')],
      ['timeline.divider.step', 'Ship it'],
      ['timeline.item', expect.stringContaining('Shipped')],
    ]);
  });

  test('read “Nothing yet” on an empty timeline', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.make({ state: 'draft', members: [me.handle!] });
    await timeline.open(id);

    await expect(timeline.empty).toHaveText('Nothing yet');
    await expect(timeline.items).toHaveCount(0);
  });
});

test.describe('The opening', () => {
  test('is the words verbatim, “You started this project · <time>” over them, beside your avatar, with no head', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn({ name: 'Ada Example' });
    const words = 'Let us build a recipe box.\n\n**Not bold**, and a fence:\n```decision id=D1\nnope: 1\n```';
    const id = await projects.makeWithSession({ name: makeUnique('Opening'), members: [me.handle!], opening: words });
    await timeline.open(id);

    const [opening] = (await projects.timeline(id)).items;
    await expect(timeline.openingWho).toHaveText(`You started this project · ${clock(opening.created_at)}`);
    await expect(timeline.openingWho.locator('time')).toHaveAttribute('title', stamp(opening.created_at));
    expect(await timeline.openingWords.innerText()).toBe(words);
    await expect(timeline.openingWords.locator('strong')).toHaveCount(0);
    await expect(timeline.opening.locator('.avatar')).toHaveText('AE');
    await expect(timeline.opening.getByTestId('timeline.item.head')).toHaveCount(0);
    await expect(timeline.openingMore).toHaveCount(0);
  });

  test('carries the second user’s name and avatar when she started the project', async ({ people, projects, timeline }) => {
    const ben = makeUnique('ben', 8);
    await people.other(ben, 'Ben Example');
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Hers'), members: [ben, me.handle!] });
    await timeline.open(id);

    await expect(timeline.openingWho).toContainText('Ben Example started this project · ');
    await expect(timeline.opening.locator('.avatar')).toHaveText('BE');
    await expect(timeline.opening.locator('.avatar')).toHaveAttribute('title', 'Ben Example');
  });

  test('folds long words with Show more, which unfolds them', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const words = Array.from({ length: 40 }, (_, index) => `Line ${index + 1} of what started it.`).join('\n');
    const id = await projects.makeWithSession({ name: makeUnique('Long'), members: [me.handle!], opening: words });
    await timeline.open(id);

    const cut = () => timeline.openingWords.evaluate((box) => box.scrollHeight - box.clientHeight);
    await expect(timeline.openingMore).toHaveText('Show more');
    expect(await cut()).toBeGreaterThan(0);
    await timeline.openingMore.click();
    await expect(timeline.openingMore).toHaveCount(0);
    expect(await cut()).toBe(0);
    expect(await timeline.openingWords.innerText()).toBe(words);
  });
});

test.describe('An open item', () => {
  test('heads with its kind’s icon and label and the time it was placed, the full stamp its tooltip', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Kinds'), members: [me.handle!] });
    const cases: [ItemKind, string, string, string][] = [
      ['decision', DECISION, 'Decision', 'lucide-message-circle-question'],
      ['decision', CONFIRMATION, 'Confirm', 'lucide-shield'],
      ['question', QUESTION, 'Question', 'lucide-message-circle-question'],
      ['action', ACTION, 'Action', 'lucide-hand'],
      ['notice', 'Blue and green.\n', 'Notice', 'lucide-info'],
      ['review', 'Read it through.\n', 'Review', 'lucide-book-open'],
      // A document carries its most common block's icon.
      ['document', DOCUMENT, 'Document · 3', 'lucide-hand'],
    ];
    const placed: string[] = [];
    for (const [kind, text] of cases) {
      placed.push(await projects.place(id, { kind, title: `A ${kind}`, text }));
    }
    await timeline.open(id);

    const items = (await projects.timeline(id)).items;
    for (const [index, [, , label, icon]] of cases.entries()) {
      const item = timeline.item(placed[index]);
      const read = items.find((each) => each.id === placed[index])!;
      await expect(item.kind).toHaveText(label);
      await expect(item.kind.locator('svg')).toHaveClass(new RegExp(`\\b${icon}\\b`));
      await expect(item.time).toHaveText(clock(read.created_at));
      await expect(item.time).toHaveAttribute('title', stamp(read.created_at));
      await expect(item.root).toHaveAttribute('data-state', 'open');
      await expect(item.urgent).toHaveCount(0);
      await expect(item.forUser).toHaveCount(0);
    }
    await expect(timeline.item(placed[1]).title).toHaveText('A decision');
  });

  test('carries the Urgent chip when urgent, and “for <user>” when it is for the other person', async ({
    people,
    projects,
    timeline,
  }) => {
    const ben = makeUnique('ben', 8);
    await people.other(ben, 'Ben Example');
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Chips'), members: [me.handle!, ben] });
    const urgent = await projects.place(id, { kind: 'notice', title: 'Storm', text: '---\nurgent: true\n---\n\nA storm comes.\n' });
    const hers = await projects.place(id, { kind: 'notice', title: 'Bike', text: `---\nfor: ${ben}\n---\n\nYour bike is ready.\n` });
    await timeline.open(id);

    await expect(timeline.item(urgent).urgent).toHaveText('Urgent');
    await expect(timeline.item(urgent).forUser).toHaveCount(0);
    await expect(timeline.item(hers).forUser).toHaveText('for Ben Example');
    await expect(timeline.item(hers).urgent).toHaveCount(0);
  });

  test('draws its prose as GFM, its ticket ids linked outside code, every link opening a new tab', async ({
    backendUrl,
    people,
    projects,
    timeline,
    links,
  }) => {
    await links.set({ ticket_url_template: `${backendUrl}/tickets/{id}` });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Prose'), members: [me.handle!] });
    const text = [
      'Some **bold** words and a [page](https://example.com/page).',
      '| Card | State |\n| --- | --- |\n| RB-12 | open |',
      '- one\n- ~~two~~',
      '`RB-13` stays code.',
    ].join('\n\n');
    const placed = await projects.place(id, { kind: 'notice', title: 'Prose', text });
    await timeline.open(id);

    const prose = timeline.item(placed).text;
    await expect(prose.locator('strong')).toHaveText('bold');
    const page = prose.getByRole('link', { name: 'page' });
    await expect(page).toHaveAttribute('href', 'https://example.com/page');
    await expect(page).toHaveAttribute('target', '_blank');
    await expect(prose.locator('table tbody tr')).toHaveCount(1);
    await expect(prose.locator('li')).toHaveCount(2);
    await expect(prose.locator('del')).toHaveText('two');
    const ticket = prose.locator('td').getByRole('link', { name: 'RB-12' });
    await expect(ticket).toHaveAttribute('href', `${backendUrl}/tickets/RB-12`);
    await expect(ticket).toHaveAttribute('target', '_blank');
    await expect(ticket).toHaveClass(/\bmention\b/);
    await expect(prose.locator('code')).toHaveText('RB-13');
    await expect(prose.locator('code a')).toHaveCount(0);
  });

  test('folds a long text with Show more, which unfolds it; a short one shows whole', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Fold'), members: [me.handle!] });
    const long = Array.from({ length: 30 }, (_, index) => `Paragraph ${index + 1}.`).join('\n\n');
    const folded = await projects.place(id, { kind: 'notice', title: 'Long', text: long });
    const short = await projects.place(id, { kind: 'notice', title: 'Short', text: 'Just this.\n' });
    await timeline.open(id);

    const item = timeline.item(folded);
    const last = item.text.getByText('Paragraph 30.');
    await expect(item.more).toHaveText('Show more');
    await expect(timeline.item(short).more).toHaveCount(0);
    await item.text.scrollIntoViewIfNeeded();
    await expect(last).not.toBeInViewport();
    await item.more.click();
    await expect(item.more).toHaveCount(0);
    await last.scrollIntoViewIfNeeded();
    await expect(last).toBeInViewport();
  });

  test('shows its last published text with a dashed border, a concept, while its latest save is held', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Concept'), members: [me.handle!] });
    const placed = await projects.place(id, { kind: 'notice', title: 'Palette', text: 'Blue and green.\n' });
    expect((await projects.save(placed, 'Red.\n')).held).toBe(true);
    await timeline.open(id);

    const item = timeline.item(placed);
    await expect(item.root).toHaveAttribute('data-concept', 'true');
    expect(await item.root.evaluate((element) => getComputedStyle(element).borderTopStyle)).toBe('dashed');
    await expect(item.text).toHaveText('Blue and green.');

    expect((await projects.save(placed, '---\ntitle: Palette\n---\nRed.\n')).held).toBe(false);
    await timeline.refocus();
    await expect(item.text).toHaveText('Red.');
    await expect(item.root).toHaveAttribute('data-concept', 'false');
    expect(await item.root.evaluate((element) => getComputedStyle(element).borderTopStyle)).toBe('solid');
  });
});

test.describe('A done line', () => {
  test('is its kind’s icon, its title and when it was done, your answer and its note under the title', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Lines'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    const action = await projects.place(id, { kind: 'action', title: 'Plug it in', text: ACTION });
    await projects.answer(decision, 'D1', 'Dome', 'Lighter to carry');
    await projects.markDone(action, 'A1', 'It is plugged in.');
    await timeline.open(id);

    const items = (await projects.timeline(id)).items;
    const line = timeline.item(decision);
    await expect(line.root).toHaveAttribute('data-state', 'done');
    await expect(line.head).toHaveCount(0);
    await expect(line.line.locator('.kind-icon svg')).toHaveClass(/\blucide-message-circle-question\b/);
    await expect(line.lineTitle).toHaveText('Which tent?');
    const done = items.find((item) => item.id === decision)!.done!;
    await expect(line.lineTime).toHaveText(clock(done.at));
    await expect(line.lineTime).toHaveAttribute('title', stamp(done.at));
    await expect(line.said).toHaveText('Dome · Lighter to carry');
    await expect(line.note.locator('svg')).toHaveClass(/\blucide-sticky-note\b/);
    await expect(line.said.locator('.avatar')).toHaveCount(0);

    // An action marked Done says only what was pasted back.
    await expect(timeline.item(action).said).toHaveText('It is plugged in.');
  });

  test('retells nothing Pilot did, nor anything of an ask Finish closed unanswered', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Settled'), members: [me.handle!] });
    const settled = await projects.place(id, {
      kind: 'decision',
      title: 'Which tent?',
      text: '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nanswer: Dome\nby: agent\nat: 2026-10-20T09:00:00Z\n```\n',
    });
    const unanswered = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await projects.transition(id, 'finished');
    await timeline.open(id);

    for (const [item, title] of [
      [settled, 'Which tent?'],
      [unanswered, 'Which lake?'],
    ]) {
      await expect(timeline.item(item).lineTitle).toHaveText(title);
      await expect(timeline.item(item).said).toHaveCount(0);
    }
  });

  test('puts the other person’s avatar before her answer', async ({ people, projects, timeline }) => {
    const ben = await people.signIn({ name: 'Ben Example' });
    const id = await projects.makeWithSession({ name: makeUnique('Theirs'), members: [ben.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await projects.answer(decision, 'D1', 'Tunnel');
    await people.signIn();
    await timeline.open(id);

    const said = timeline.item(decision).said;
    await expect(said).toHaveText('BETunnel');
    await expect(said.locator('.avatar')).toHaveAttribute('title', 'Ben Example');
  });
});

test.describe('Anchored to its end', () => {
  const NOTICE = 'A notice that takes\n\na few lines\n\nof the timeline.\n';

  async function longProject(projects: Projects, member: string, name: string): Promise<string> {
    const id = await projects.makeWithSession({ name, members: [member] });
    for (let index = 0; index < 8; index += 1) {
      await projects.place(id, { kind: 'notice', title: `Notice ${index + 1}`, text: NOTICE });
    }
    return id;
  }

  test('a short timeline sits at the bottom', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Short'), members: [me.handle!] });
    await timeline.open(id);

    const feed = (await timeline.root.boundingBox())!;
    const opening = (await timeline.opening.boundingBox())!;
    expect(opening.y).toBeGreaterThan(feed.y + feed.height / 2);
    expect(feed.y + feed.height - (opening.y + opening.height)).toBeLessThan(100);
  });

  test('opens at its end, follows new items there with a flash, and stays where the reader scrolled', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await longProject(projects, me.handle!, makeUnique('Anchor'));
    await timeline.open(id);
    // The first read flashes nothing: counted at once, before a flash could have ended.
    expect(await timeline.root.locator('.fresh').count()).toBe(0);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    expect(await timeline.scrollTop()).toBeGreaterThan(0);

    const arrived = await projects.place(id, { kind: 'notice', title: 'Arrived', text: NOTICE });
    await timeline.refocus();
    const item = timeline.item(arrived);
    await expect(item.root).toHaveClass(/\bfresh\b/);
    await expect(item.root).toBeInViewport();
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    await expect(timeline.items.first()).not.toHaveClass(/\bfresh\b/);
    await expect(item.root).not.toHaveClass(/\bfresh\b/);

    await timeline.scrollToTop();
    const later = await projects.place(id, { kind: 'notice', title: 'Later', text: NOTICE });
    await timeline.refocus();
    await expect(timeline.item(later).root).toHaveClass(/\bfresh\b/);
    expect(await timeline.scrollTop()).toBe(0);
    await expect(timeline.item(later).root).not.toBeInViewport();
  });

  test('stands at its end on every project it switches to', async ({ page, people, projects, projectList, timeline }) => {
    const me = await people.signIn();
    const first = makeUnique('First');
    const second = makeUnique('Second');
    const firstId = await longProject(projects, me.handle!, first);
    const secondId = await longProject(projects, me.handle!, second);
    await timeline.open(firstId);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    await timeline.scrollToTop();

    await projectList.tab(second).click();
    await expect(page).toHaveURL(`/projects/${secondId}`);
    await expect(timeline.items).toHaveCount(8);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    await timeline.scrollToTop();

    await projectList.tab(first).click();
    await expect(page).toHaveURL(`/projects/${firstId}`);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
  });
});

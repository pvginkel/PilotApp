/**
 * A project's timeline (F8): its items in their order under their date and step dividers (F9); the
 * opening (F18.1, F18.2); an item's head (F12, F10.1, F107, F114); its prose as GFM, linked, folding
 * when long (F29.1, F12.2); a concept (F78); the done line (F13.1, F13.2); a step's long name cut
 * on a phone; a short timeline at its top, no band under its last item; opened at its end, following
 * what arrives there, a new item flashing, and at its end on each project (F8.2, F1.6); the reader's
 * own Show more growing downward.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { projectAddress, type Projects } from '../support/projects';
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
    // Off a phone the chip stands in the head's line, its icon the phone's alone.
    await expect(timeline.item(hers).forUser.locator('svg')).toBeHidden();
    const [kind, chip] = await Promise.all([timeline.item(hers).kind.boundingBox(), timeline.item(hers).forUser.boundingBox()]);
    expect(Math.abs(chip!.y + chip!.height / 2 - (kind!.y + kind!.height / 2))).toBeLessThan(2);
  });

  test('draws its prose as GFM, a single `~` striking nothing, its ticket ids linked outside code, every link opening a new tab', async ({
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
      'It takes [!-~]+ before the colon and [!-~]+ after it.',
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
    // Only a double `~` strikes text out; two single ones are drawn as written.
    await expect(prose.locator('del')).toHaveText(['two']);
    await expect(prose.locator('p', { hasText: 'It takes' })).toHaveText('It takes [!-~]+ before the colon and [!-~]+ after it.');
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
    // A button drawn as a link never underlines.
    await item.more.hover();
    expect(await item.more.evaluate((element) => getComputedStyle(element).textDecorationLine)).toBe('none');
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

test.describe('On a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('cuts a step’s long name at the divider’s end, and the timeline scrolls only down', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const title = 'Build the card that shows every running session of the fleet, its environment and its turn';
    const id = await projects.makeWithSession({
      name: makeUnique('Long step'),
      members: [me.handle!],
      tasks: [{ id: 'build', title, status: 'in_progress' }],
    });
    await projects.place(id, { kind: 'notice', title: 'Built one', text: '---\nstep: build\n---\n\nOne.\n' });
    await timeline.open(id);

    const name = timeline.root.getByTestId('timeline.divider.step').locator('.name');
    await expect(name).toHaveText(title);
    expect(await name.evaluate((element) => [element.scrollWidth > element.clientWidth, getComputedStyle(element).textOverflow])).toEqual([
      true,
      'ellipsis',
    ]);
    expect(await timeline.root.evaluate((feed) => feed.scrollWidth - feed.clientWidth)).toBeLessThanOrEqual(0);
  });

  test('leaves no band under the last item at its end: 12 px of the column’s padding', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Foot'), members: [me.handle!] });
    for (let index = 0; index < 8; index += 1) {
      await projects.place(id, { kind: 'notice', title: `Notice ${index + 1}`, text: 'A notice that takes\n\na few lines.\n' });
    }
    await timeline.open(id);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);

    expect(await timeline.root.locator('.feed-inner').evaluate((inner) => getComputedStyle(inner).padding)).toBe('12px');
    const feed = (await timeline.root.boundingBox())!;
    const last = (await timeline.items.last().boundingBox())!;
    // The column's padding and the item's own margin.
    expect(Math.abs(feed.y + feed.height - (last.y + last.height) - (12 + 8))).toBeLessThan(1.5);
  });
});

test.describe('Anchored to its end', () => {
  const NOTICE = 'A notice that takes\n\na few lines\n\nof the timeline.\n';
  // Long enough to fold, its Show more under it.
  const LONG = Array.from({ length: 24 }, (_, index) => `Paragraph ${index + 1} of the long notice.`).join('\n\n') + '\n';

  async function longProject(projects: Projects, member: string, name: string): Promise<string> {
    const id = await projects.makeWithSession({ name, members: [member] });
    for (let index = 0; index < 8; index += 1) {
      await projects.place(id, { kind: 'notice', title: `Notice ${index + 1}`, text: NOTICE });
    }
    return id;
  }

  test('a short timeline stands at its top', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Short'), members: [me.handle!] });
    await timeline.open(id);

    const feed = (await timeline.root.boundingBox())!;
    const [first, opening] = await Promise.all([timeline.rows.first().boundingBox(), timeline.opening.boundingBox()]);
    // The column's padding and the day divider's margin above it.
    expect(Math.abs(first!.y - feed.y - (20 + 26))).toBeLessThan(1.5);
    expect(opening!.y + opening!.height).toBeLessThan(feed.y + feed.height / 2);
  });

  test('leaves no band under the last item at its end: 20 px of the column’s padding', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await longProject(projects, me.handle!, makeUnique('Foot'));
    await timeline.open(id);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);

    expect(await timeline.root.locator('.feed-inner').evaluate((inner) => getComputedStyle(inner).padding)).toBe('20px 24px');
    const feed = (await timeline.root.boundingBox())!;
    const last = (await timeline.items.last().boundingBox())!;
    // The column's padding and the item's own margin.
    expect(Math.abs(feed.y + feed.height - (last.y + last.height) - (20 + 8))).toBeLessThan(1.5);
  });

  test('at its end, follows long items arriving to the end of their Show more, three in a row', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await longProject(projects, me.handle!, makeUnique('Long arrivals'));
    await timeline.open(id);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);

    const arrived: string[] = [];
    for (let index = 0; index < 3; index += 1) {
      arrived.push(await projects.place(id, { kind: 'notice', title: `Long ${index + 1}`, text: LONG }));
    }
    for (const each of arrived) await expect(timeline.item(each).more).toBeAttached();
    await expect(timeline.item(arrived[2]).more).toBeInViewport();
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
  });

  test('the reader’s own Show more at its end unfolds downward, and the timeline no longer follows its end', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await longProject(projects, me.handle!, makeUnique('Own'));
    const long = await projects.place(id, { kind: 'notice', title: 'Long', text: LONG });
    await timeline.open(id);
    const item = timeline.item(long);
    await expect(item.more).toBeInViewport();
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    const top = await timeline.scrollTop();
    const head = (await item.head.boundingBox())!;

    await item.more.click();
    await expect(item.more).toHaveCount(0);
    await expect.poll(() => timeline.fromEnd()).toBeGreaterThan(100);
    expect(await timeline.scrollTop()).toBe(top);
    expect(Math.abs((await item.head.boundingBox())!.y - head.y)).toBeLessThan(1);

    const later = await projects.place(id, { kind: 'notice', title: 'Later', text: NOTICE });
    await expect(timeline.item(later).root).toBeAttached();
    expect(await timeline.scrollTop()).toBe(top);
    await expect(timeline.item(later).root).not.toBeInViewport();
  });

  test('a block the reader opened at its end and closed again leaves the timeline at its end, following what arrives', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await longProject(projects, me.handle!, makeUnique('Closed again'));
    const options = ['Dome', 'Tunnel', 'Tarp', 'Bivvy', 'Hammock', 'Van'].map((option) => `  - ${option}\n`).join('');
    const decision = await projects.place(id, {
      kind: 'decision',
      title: 'Which tent?',
      text: `\`\`\`decision id=D1\noptions:\n${options}answer: Dome\nby: agent\nat: 2026-10-20T09:00:00Z\n\`\`\`\n`,
    });
    await timeline.open(id);
    const { block } = timeline.item(decision);
    await expect(block.toggle).toBeInViewport();
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);

    await block.toggle.click();
    await expect(block.options).toHaveCount(6);
    await expect.poll(() => timeline.fromEnd()).toBeGreaterThan(100);
    await block.toggle.click();
    await expect(block.options).toHaveCount(1);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);

    const later = await projects.place(id, { kind: 'notice', title: 'Later', text: NOTICE });
    await expect(timeline.item(later).root).toBeAttached();
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
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
    await expect(page).toHaveURL(projectAddress(secondId));
    await expect(timeline.items).toHaveCount(8);
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
    await timeline.scrollToTop();

    await projectList.tab(first).click();
    await expect(page).toHaveURL(projectAddress(firstId));
    await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
  });
});

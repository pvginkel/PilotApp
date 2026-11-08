/**
 * The brain's waits on the timeline (F27, F12.1, F13.9). A card wait open shows its kind's ticket
 * and *Wait*, its cards as ticket links and the states it waits for, since when it waits, and its
 * firings, one line each, with what Pilot did with it: its turn while its run is to run or runs,
 * *left open* once the run's turn ended with the wait open; each arrives on the open timeline as it
 * lands. A timed wait open shows its hourglass and its due time from now in one coarse unit, *Due
 * now* under a minute, its full stamp the tooltip, and once its due time fired it, how long ago and
 * Pilot's turn. The head's one button, touching Discuss, is *Check now* on a card wait and *Skip
 * wait* on a timed wait, its label its tooltip; a press records the person's request, which fires
 * the wait, and while Pilot is checking it is disabled, the reason its tooltip. Pilot's close
 * leaves the line its title, its time and the note under it, with no Open and no Undo, its title
 * opening nothing; Finish's leaves no note. On a phone a tap on a wait's line opens a menu of its
 * actions under it, Discuss alone, which a tap elsewhere closes.
 */

import type { Locator } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique, makeUniqueToken } from '../support/helpers';
import { projectAddress } from '../support/projects';

// The browser's time zone, which every time on the timeline is shown in.
const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });

const fullStamp = (at: string) =>
  new Intl.DateTimeFormat('en-GB', { dateStyle: 'full', timeStyle: 'long', timeZone: ZONE }).format(new Date(at));

const MINUTE = 60_000;
const CLOCK = '\\d\\d:\\d\\d';
const PHONE = { width: 390, height: 844 };
const NOTE = 'The card read Done at 09:40; the rollout goes on';

/** A tracker's project key of the spec's own, so that no other spec's wait watches its cards. */
const keyOf = () => `W${makeUniqueToken(6).toUpperCase()}`;

// eslint-disable-next-line no-restricted-properties -- A wait's times are real ones, counted from now.
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
// eslint-disable-next-line no-restricted-properties -- A wait's times are real ones, counted from now.
const ahead = (ms: number) => new Date(Date.now() + ms).toISOString();

test.describe('A card wait', () => {
  test('shows its cards as ticket links, the states it waits for and since when; a State change of one of its cards adds its firing, Pilot’s turn, then left open once its run’s turn ended', async ({
    backendUrl,
    people,
    projects,
    timeline,
    links,
    waits,
    chats,
    controller,
  }) => {
    await links.set({ ticket_url_template: `${backendUrl}/tickets/{id}` });
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Rollout'), members: [me.handle!] });
    const key = keyOf();
    const wait = await waits.add(id, {
      kind: 'card_wait',
      title: 'The night shift takes the cards',
      cards: [`${key}-1`, `${key}-4`],
      states: ['Done', "Won't fix"],
    });
    const { created_at } = await projects.item(id, wait);
    await timeline.open(id);
    const item = timeline.item(wait);

    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.root).toHaveAttribute('data-kind', 'card_wait');
    await expect(item.kind).toHaveText('Wait');
    await expect(item.kind.locator('svg')).toHaveClass(/\blucide-ticket\b/);
    await expect(item.title).toHaveText('The night shift takes the cards');
    await expect(item.wait.on).toHaveText(`${key}-1, ${key}-4 → Done or Won't fix`);
    await expect(item.wait.cards.getByRole('link')).toHaveText([`${key}-1`, `${key}-4`]);
    await expect(item.wait.cards.getByRole('link').last()).toHaveAttribute('href', `${backendUrl}/tickets/${key}-4`);
    await expect(item.wait.since).toHaveText(new RegExp(`^Waiting since ${CLOCK}$`));
    await expect(item.wait.since.locator('time')).toHaveAttribute('title', fullStamp(created_at));
    await expect(item.wait.firings).toHaveCount(0);
    await expect(item.wait.request).toBeEnabled();

    expect(await waits.transition({ card: `${key}-4`, from: 'In Progress', to: 'Done', by: 'pieter' })).toBe(1);
    await expect(item.wait.firings).toHaveText([new RegExp(`^${key}-4 → Done · ${CLOCK} · Pilot’s turn$`)]);
    await expect(item.wait.firings.getByRole('link')).toHaveAttribute('href', `${backendUrl}/tickets/${key}-4`);
    const [firing] = (await projects.item(id, wait)).wait!.firings;
    await expect(item.wait.firings.locator('time')).toHaveAttribute('title', fullStamp(firing.fired_at));
    await expect(item.wait.request).toBeDisabled();
    await expect(item.wait.request).toHaveAttribute('title', 'Pilot is checking');

    const opened = await chats.opening(id);
    await waits.run(wait);
    const session = await opened();
    await controller.finish(chats.store, session);
    await expect(item.wait.firings).toHaveText([new RegExp(`^${key}-4 → Done · ${CLOCK} · left open$`)]);
    await expect(item.wait.request).toBeEnabled();
    await expect(item.wait.request).toHaveAttribute('title', 'Check now');
  });

  test('ends a firing’s line at its time when the run that took it failed, Pilot having done nothing with it', async ({
    projects,
    people,
    timeline,
    waits,
    chats,
    controller,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Failed'), members: [me.handle!] });
    const key = keyOf();
    const wait = await waits.add(id, { kind: 'card_wait', title: 'The card is done', cards: [`${key}-2`], states: ['Done'] });
    await timeline.open(id);
    const item = timeline.item(wait);

    expect(await waits.transition({ card: `${key}-2`, from: 'In Progress', to: 'Done', by: 'pieter' })).toBe(1);
    await expect(item.wait.firings).toHaveText([new RegExp(`^${key}-2 → Done · ${CLOCK} · Pilot’s turn$`)]);

    const opened = await chats.opening(id);
    await waits.run(wait);
    const session = await opened();
    await controller.finish(chats.store, session, 'error', 'The model is overloaded.');
    await expect(item.wait.firings).toHaveText([new RegExp(`^${key}-2 → Done · ${CLOCK}$`)]);
    await expect(item.root.getByTestId('timeline.wait.outcome')).toHaveCount(0);
  });
});

test.describe('The request’s button', () => {
  test('is an icon in the head touching Discuss, its label its tooltip, Check now on a card wait; a press records the person’s request, Pilot checking until the run it fired ends', async ({
    people,
    projects,
    timeline,
    waits,
    chats,
    controller,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Checked'), members: [me.handle!] });
    const wait = await waits.add(id, { kind: 'card_wait', title: 'The card is done', cards: [`${keyOf()}-7`], states: ['Done'] });
    await timeline.open(id);
    const item = timeline.item(wait);
    const { request, firings } = item.wait;

    await expect(request).toHaveAttribute('title', 'Check now');
    await expect(request).toHaveAttribute('aria-label', 'Check now');
    await expect(request).toHaveText('');
    await expect(request.locator('svg path')).toHaveCount(6);
    await touching(request, item.discuss);

    await request.click();
    await expect(firings).toHaveText([new RegExp(`^Check requested by ${me.handle} · ${CLOCK} · Pilot’s turn$`)]);
    await expect(request).toBeDisabled();
    await expect(request).toHaveAttribute('title', 'Pilot is checking');

    const opened = await chats.opening(id);
    await waits.run(wait);
    const session = await opened();
    await expect(request).toHaveAttribute('title', 'Pilot is checking');
    await controller.finish(chats.store, session);
    await expect(firings).toHaveText([new RegExp(`^Check requested by ${me.handle} · ${CLOCK} · left open$`)]);
    await expect(request).toBeEnabled();
  });

  test('is Skip wait on a timed wait, whose press records the request beside its due time', async ({ people, projects, timeline, waits }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Skipped'), members: [me.handle!] });
    const wait = await waits.add(id, { kind: 'timed_wait', title: 'The certificate is issued', due_at: ahead(3 * 60 * MINUTE) });
    await timeline.open(id);
    const item = timeline.item(wait);

    await expect(item.wait.request).toHaveAttribute('title', 'Skip wait');
    await expect(item.wait.request).toHaveAttribute('aria-label', 'Skip wait');
    await item.wait.request.click();
    await expect(item.wait.firings).toHaveText([new RegExp(`^Skip requested by ${me.handle} · ${CLOCK} · Pilot’s turn$`)]);
    await expect(item.wait.due).toHaveText('Due in 3 hours');
    await expect(item.wait.request).toBeDisabled();
    await expect(item.wait.request).toHaveAttribute('title', 'Pilot is checking');
  });
});

test.describe('A timed wait', () => {
  test('shows its hourglass and its due time from now in one coarse unit, Due now under a minute, its full stamp the tooltip', async ({
    people,
    projects,
    timeline,
    waits,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Due'), members: [me.handle!] });
    // A margin of seconds either side of the unit, so that the count stands while the spec reads it.
    const spans: [number, string][] = [
      [7 * MINUTE + 20_000, 'Due in 7 minutes'],
      [5 * 60 * MINUTE + MINUTE, 'Due in 5 hours'],
      [3 * 24 * 60 * MINUTE + 60 * MINUTE, 'Due in 3 days'],
      [2 * 7 * 24 * 60 * MINUTE + 60 * MINUTE, 'Due in 2 weeks'],
      [40_000, 'Due now'],
    ];
    const placed = [];
    for (const [span, words] of spans) {
      const wait = await waits.add(id, { kind: 'timed_wait', title: words, due_at: ahead(span) });
      placed.push({ wait, words, due: (await projects.item(id, wait)).wait!.due_at! });
    }
    await timeline.open(id);

    for (const { wait, words, due } of placed) {
      const item = timeline.item(wait);
      await expect(item.root).toHaveAttribute('data-kind', 'timed_wait');
      await expect(item.kind).toHaveText('Wait');
      await expect(item.kind.locator('svg')).toHaveClass(/\blucide-hourglass\b/);
      await expect(item.wait.due).toHaveText(words);
      await expect(item.wait.due.locator('time')).toHaveAttribute('title', fullStamp(due));
      await expect(item.wait.on).toHaveCount(0);
      await expect(item.wait.since).toHaveCount(0);
      await expect(item.wait.firings).toHaveCount(0);
    }
  });

  test('past its due time and fired, reads how long ago it was due and that it is Pilot’s turn', async ({ people, projects, timeline, waits }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Overdue'), members: [me.handle!] });
    const wait = await waits.add(id, {
      kind: 'timed_wait',
      title: 'The rollout settles',
      placed_at: ago(10 * MINUTE),
      due_at: ago(5 * MINUTE - 10_000),
    });
    await waits.due();
    await timeline.open(id);
    const item = timeline.item(wait);

    await expect(item.wait.due).toHaveText('Due 5 minutes ago · Pilot’s turn');
    await expect(item.wait.firings).toHaveCount(0);
    await expect(item.wait.request).toBeDisabled();
    await expect(item.wait.request).toHaveAttribute('title', 'Pilot is checking');
  });
});

test.describe('A wait done', () => {
  test('by Pilot is its line: its title, the time and the note, with Discuss and no Open or Undo, its title opening nothing; by Finish, no note', async ({
    page,
    people,
    projects,
    timeline,
    waits,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Closed'), members: [me.handle!] });
    const marked = await waits.add(id, { kind: 'card_wait', title: 'The rollout card is done', cards: [`${keyOf()}-2`], states: ['Done'] });
    const finished = await waits.add(id, { kind: 'timed_wait', title: 'The backup has run', due_at: ahead(60 * MINUTE) });
    await waits.close(marked, NOTE);
    await timeline.open(id);
    const item = timeline.item(marked);

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineTitle).toHaveText('The rollout card is done');
    await expect(item.lineTime).toHaveText(new RegExp(`^${CLOCK}$`));
    await expect(item.wait.note).toHaveText(NOTE);
    await item.line.hover();
    await expect(item.lineDiscuss).toBeVisible();
    await expect(item.open).toHaveCount(0);
    await expect(item.undo).toHaveCount(0);
    await expect(item.wait.request).toHaveCount(0);
    await item.lineTitle.click();
    await expect(page).toHaveURL(projectAddress(id));

    await projects.transition(id, 'finished');
    const other = timeline.item(finished);
    await expect(other.root).toHaveAttribute('data-state', 'done');
    await expect(other.lineTitle).toHaveText('The backup has run');
    await expect(other.wait.note).toHaveCount(0);
    await expect(other.undo).toHaveCount(0);
  });
});

test.describe('A wait’s done line on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('a tap on it opens the menu of its actions under it, Discuss alone and no Undo, which a tap elsewhere closes; its Discuss quotes the wait into the chat', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    waits,
    chat,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Menu'), members: [me.handle!] });
    const wait = await waits.add(id, { kind: 'card_wait', title: 'The card is done', cards: [`${keyOf()}-3`], states: ['Done'] });
    await waits.close(wait, NOTE);
    await timeline.open(id);
    const item = timeline.item(wait);

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.undo).toHaveCount(0);
    await expect(item.lineDiscuss).toHaveCount(0);
    await expect(item.lineMenu).toHaveCount(0);
    await item.lineTitle.tap();
    await expect(item.lineMenu.getByRole('menuitem')).toHaveText(['Discuss']);
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(projectAddress(id));
    await item.lineTitle.tap();
    await expect(item.lineMenu).toHaveCount(0);

    await item.lineTitle.tap();
    await expect(item.lineMenu).toBeVisible();
    await timeline.root.tap({ position: { x: 4, y: 4 } });
    await expect(item.lineMenu).toHaveCount(0);

    await item.wait.note.tap();
    await item.lineMenuDiscuss.tap();
    await expect(phoneTabs.tab('chat')).toHaveAttribute('aria-selected', 'true');
    await expect(chat.quote).toHaveAttribute('data-quote', `item ${wait}`);
  });
});

/** Two icon buttons side by side touch: no gap stands between their boxes. */
async function touching(left: Locator, right: Locator): Promise<void> {
  const [a, b] = await Promise.all([left.boundingBox(), right.boundingBox()]);
  expect(Math.abs(a!.x + a!.width - b!.x)).toBeLessThan(1);
}

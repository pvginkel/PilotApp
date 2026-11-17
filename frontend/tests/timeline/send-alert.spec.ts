/**
 * Pilot's alert on a document (F168.6): where another open ask has to be answered before the
 * document is sent, a rounded gold box as the halt's popover is, the document's width — opened, the
 * last line of its head under the segment bar, not scrolling with its body; inline, the document's
 * top — its triangle, what to answer first and what the Send starts, and the popover's button, which
 * opens the ask it names. On a one-ask item on the timeline it stands at the top of its panel, over
 * Pilot's note on its block, Pilot's note on the item under it. On a phone one line, cut with an
 * ellipsis, a chevron; a tap opens and closes it, and it is closed each time the document opens. It
 * goes once the item of the ask it names is done, live, and blocks nothing. None stands on a
 * document that is Pilot's (`tests/work/claimed.spec.ts`).
 */

import type { Locator } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import type { Projects } from '../support/projects';
import { addressOf } from '../support/page-objects/timeline-page';

const FIELD = '```decision id=D1\noptions:\n  - North field\n  - South field\nrecommend: North field\n```\n';
const GEAR = [
  '## The tent\n',
  '```decision id=D1\noptions:\n  - Rent\n  - Borrow\nrecommend: Rent\n```\n',
  '## The stove\n',
  '```decision id=D2\noptions:\n  - Gas\n  - Spirit\nrecommend: Gas\n```\n',
].join('\n');
const FIRST = 'Answer Which field? first: sending this books the gear for the field it names.';
const ALERT = `Answer **Which field?** first: sending this books the gear for the field it names.\n\nThe rental closes its list on Thursday.`;
const PHONE = { width: 390, height: 844 };
const STOVE = '```decision id=D1\noptions:\n  - Gas\n  - Spirit\nrecommend: Gas\n```\n';
const SHOP = 'The camping shop in town sells gas cartridges only.';
const SPIRIT = 'Spirit burns slower in the wind.';

const box = async (locator: Locator) => (await locator.boundingBox())!;

/** A project with the one-ask decision to answer first and a document whose Send waits on it, `text` before its block. */
async function alerted(projects: Projects, handle: string, text: string) {
  const project = await projects.makeWithSession({ name: makeUnique('Alerted'), members: [handle] });
  const field = await projects.place(project, { kind: 'decision', title: 'Which field?', text: FIELD });
  const gear = await projects.place(project, { kind: 'document', title: 'The gear', text: `${text}\n\n${GEAR}` });
  await projects.alert(gear, { text: ALERT, awaits: `${field}/D1` });
  return { project, field, gear };
}

const LONG = 'We walk the north shore to the ridge and camp below it. '.repeat(60);

test.describe('Pilot’s alert on a document', () => {
  test('stands as the opened document’s head’s last line, under the segment bar, across its width, not scrolling with its body: its triangle, its text and the button that opens the ask to answer first; it blocks nothing', async ({
    page,
    people,
    projects,
    overlay,
  }) => {
    const me = await people.signIn();
    const { project, field, gear } = await alerted(projects, me.handle!, LONG);
    await overlay.open(project, gear);

    const alert = overlay.alert;
    await expect(alert.root).toBeVisible();
    expect(await overlay.head.locator('> *').last().getAttribute('data-testid')).toBe('timeline.item.send-alert');
    await expect(alert.root).toHaveClass(/\bgold-line\b/);
    await expect(alert.root.locator('> svg')).toHaveCount(1);
    await expect(alert.text.locator('p')).toHaveText([FIRST, 'The rental closes its list on Thursday.']);
    await expect(alert.go).toHaveText('Which field?');
    await expect(alert.go).toHaveAttribute('title', 'Go to D1 of “Which field?”, to answer it first');
    await expect(alert.toggle).toHaveCount(0);
    const [shown, bar, title, discuss] = await Promise.all([box(alert.root), box(overlay.segments.first()), box(overlay.title), box(overlay.discuss)]);
    expect(shown.y).toBeGreaterThan(bar.y + bar.height);
    expect(Math.abs(shown.x - title.x)).toBeLessThanOrEqual(1);
    expect(shown.x + shown.width).toBeGreaterThanOrEqual(discuss.x + discuss.width - 1);

    await overlay.body.evaluate((body) => body.scrollTo(0, body.scrollHeight));
    await expect.poll(() => overlay.body.evaluate((body) => body.scrollTop)).toBeGreaterThan(0);
    expect((await box(alert.root)).y).toBe(shown.y);

    // Nothing waits on it.
    await expect(overlay.send).toBeEnabled();
    await alert.go.click();
    await expect(page).toHaveURL(addressOf(project, field, 'D1'));
  });

  test('stands at an inline document’s top, and goes, live, once the item of the ask it names is done', async ({
    people,
    projects,
    timeline,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const { project, field, gear } = await alerted(projects, me.handle!, 'Pack for the weekend.');
    await timeline.open(project);
    await deploymentSse.ensureConnected();

    const item = timeline.item(gear);
    expect(await item.document.locator('> *').first().getAttribute('data-testid')).toBe('timeline.item.send-alert');
    await expect(item.alert.text.locator('p').first()).toHaveText(FIRST);
    await expect(item.alert.go).toHaveText('Which field?');
    await expect(item.send).toBeEnabled();

    await projects.answer(field, 'D1', 'South field');
    await expect(timeline.item(field).root).toHaveAttribute('data-state', 'done');
    await expect(item.alert.root).toHaveCount(0);
    await expect(item.blockAt('D1').option('Rent')).toBeVisible();
  });
});

test.describe('Pilot’s alert on a one-ask item', () => {
  test('stands at the top of its panel on the timeline, over Pilot’s note on its block, Pilot’s note on the item under it; it blocks nothing and goes once the ask it names is done', async ({
    people,
    projects,
    timeline,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const project = await projects.makeWithSession({ name: makeUnique('Alerted'), members: [me.handle!] });
    const field = await projects.place(project, { kind: 'decision', title: 'Which field?', text: FIELD });
    const stove = await projects.place(project, { kind: 'decision', title: 'Which stove?', text: STOVE });
    await projects.alert(stove, { text: ALERT, awaits: `${field}/D1` });
    await projects.note(stove, { text: SHOP });
    await projects.note(stove, { block: 'D1', text: SPIRIT, suggested_answer: 'Spirit' });
    await timeline.open(project);
    await deploymentSse.ensureConnected();

    const item = timeline.item(stove);
    const panel = () => item.block.root.locator('> *').evaluateAll((parts) => parts.map((part) => part.className));
    expect(await panel()).toEqual(['gold-line doc-alert', 'pilot-note doc', 'pilot-note', 'block-controls']);
    await expect(item.alert.text.locator('p').first()).toHaveText(FIRST);
    await expect(item.alert.go).toHaveText('Which field?');
    await expect(item.pilotsNote.text).toHaveText(SHOP);
    await expect(item.pilotsNote.mark).toHaveAttribute('title', 'Pilot’s own note on this document, not the writer’s');
    await expect(item.block.pilotsNote.text).toHaveText(SPIRIT);
    // Nothing waits on it.
    await item.block.option('Gas').click();
    await expect(item.block.answerSend).toBeEnabled();

    await projects.answer(field, 'D1', 'South field');
    await expect(timeline.item(field).root).toHaveAttribute('data-state', 'done');
    await expect(item.alert.root).toHaveCount(0);
    expect(await panel()).toEqual(['pilot-note doc', 'pilot-note', 'block-controls']);
  });
});

test.describe('Pilot’s alert on a phone', () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test('is one line, cut with an ellipsis, with a chevron; a tap opens and closes it, and it is closed each time the document opens', async ({
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const { project, gear } = await alerted(projects, me.handle!, LONG);
    await overlay.open(project, gear);

    const alert = overlay.alert;
    const first = alert.text.locator('p').first();
    await expect(alert.root).toHaveAttribute('data-open', 'false');
    await expect(alert.toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(first).toHaveCSS('white-space', 'nowrap');
    await expect(first).toHaveCSS('text-overflow', 'ellipsis');
    expect(await first.evaluate((line) => line.scrollWidth > line.clientWidth)).toBe(true);
    await expect(alert.text.locator('p').last()).toBeHidden();
    await expect(alert.go).toBeHidden();

    await alert.text.tap();
    await expect(alert.root).toHaveAttribute('data-open', 'true');
    await expect(alert.toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(alert.text.locator('p').last()).toBeVisible();
    await expect(alert.go).toBeVisible();
    expect(await first.evaluate((line) => line.scrollWidth > line.clientWidth)).toBe(false);
    await alert.toggle.tap();
    await expect(alert.root).toHaveAttribute('data-open', 'false');
    await expect(alert.go).toBeHidden();

    await alert.text.tap();
    await expect(alert.root).toHaveAttribute('data-open', 'true');
    await overlay.back.tap();
    await timeline.item(gear).card.open.tap();
    await expect(alert.root).toHaveAttribute('data-open', 'false');
  });
});

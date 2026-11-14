/**
 * A confirmation (F22): a compact yellow card, its reason line with the ground as tooltip (F22.1),
 * drawn as an action is: the title, the proposal as its text, full width, and under it Yes and No,
 * plain buttons in its block, neither tinted, no paste-back and no Other (F22.2, F17.3), each only
 * chosen, the one chosen a soft button, until the block's Send (F32.3), its answer read as an
 * action's; No opening a console whose reason may stay empty and is the note (F22.3), with no Send
 * of its own, in the growing field kept until sent (F115, F110, F133); Details / Less unfolding the prose, on the
 * left and never underlined (F22.4); its done line led by a check or a cross, both in the primary
 * as a kind's icon is, with the reason (F22.5); and done, its answer alone, opening on its chevron to its proposal and Yes and No,
 * standing and taking nothing (F31.2).
 */

import { cssColour } from '../support/contrast';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { slowNetwork } from '../support/network';

const BEFORE = 'The tag is cut and the notes are written.';
const AFTER = 'The push carries two commits.';
const BLOCK = '```decision id=C1\ntype: confirmation\nproposal: Push the release to production\nbecause: auto-pilot-off\n```\n';
const CONFIRMATION = `${BEFORE}\n\n${BLOCK}\n${AFTER}\n`;
const PILOTS =
  '```decision id=C1\ntype: confirmation\nproposal: Push the release to production\nbecause: auto-pilot-off\n' +
  'answer: Yes\nby: agent\nat: 2026-10-20T09:00:00Z\nnote: The checks are green.\n```\n';
const UNSENT_KEY = 'pilot.unsent';

test.describe('A confirmation', () => {
  test('is a compact yellow card drawn as an action: its reason line, the title, the proposal its text, full width, Yes and No plain buttons in its block under it, Send at their row’s end, no paste-back, no Other, the prose folded', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Card'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: CONFIRMATION });
    await timeline.open(id);
    const item = timeline.item(confirmation);
    const { confirm } = item;

    await expect(item.root).toHaveClass(/\bconfirm\b/);
    expect(await item.root.evaluate((element) => getComputedStyle(element).backgroundImage)).toContain('linear-gradient');
    await expect(item.kind).toHaveText('Confirm');
    await expect(item.kind.locator('svg')).toHaveClass(/\blucide-shield\b/);
    await expect(item.why).toHaveText('Auto pilot off');
    await expect(item.why).toHaveAttribute('title', 'Pilot asks because auto pilot is off; under auto pilot it would go ahead');
    await expect(item.title).toHaveText('Ship 1.2?');
    await expect(confirm.proposal).toHaveText('Push the release to production');
    await expect(item.block.root).toHaveAttribute('data-block-id', 'C1');
    await expect(item.block.head).toHaveCount(0);
    await expect(confirm.yes).toHaveText('Yes');
    await expect(confirm.yes).toHaveAttribute('title', 'Yes: Push the release to production');
    await expect(confirm.no).toHaveText('No');
    await expect(confirm.no).toHaveAttribute('title', 'No, and say why');
    // An action's options in an item of its own: plain buttons, neither the primary, green nor red.
    await expect(confirm.yes).toHaveClass('btn');
    await expect(confirm.no).toHaveClass('btn');
    // The block's Send, the primary, waits for the choice.
    await expect(confirm.answerSend).toHaveText('Send');
    await expect(confirm.answerSend).toHaveClass(/\bbtn-primary\b/);
    await expect(confirm.answerSend.locator('svg')).toHaveClass(/\blucide-send\b/);
    await expect(confirm.answerSend).toBeDisabled();
    await expect(item.block.root.locator('button')).toHaveCount(3);
    await expect(item.block.paste).toHaveCount(0);
    await expect(item.block.other).toHaveCount(0);

    // The proposal is the card's text: the title's colour, the card's whole width, over its block.
    const colour = (element: Element) => getComputedStyle(element).color;
    expect(await confirm.proposal.evaluate(colour)).toBe(await item.title.evaluate(colour));
    const text = (await confirm.proposal.boundingBox())!;
    const title = (await item.title.boundingBox())!;
    const panel = (await item.block.root.boundingBox())!;
    expect(text.x).toBeCloseTo(title.x, 0);
    expect(text.width).toBeCloseTo(title.width, 0);
    expect(panel.y).toBeGreaterThanOrEqual(text.y + text.height);
    // Yes and No stand in one row inside it, Yes first.
    const yes = (await confirm.yes.boundingBox())!;
    const no = (await confirm.no.boundingBox())!;
    expect(yes.y).toBeGreaterThan(panel.y);
    expect(no.y).toBeCloseTo(yes.y, 0);
    expect(no.x).toBeGreaterThan(yes.x + yes.width);
    // Send ends their row, at its right.
    const send = (await confirm.answerSend.boundingBox())!;
    const row = (await item.block.root.locator('.item-actions').boundingBox())!;
    expect(send.y).toBeCloseTo(yes.y, 0);
    expect(send.x + send.width).toBeCloseTo(row.x + row.width, 0);
    expect(send.x).toBeGreaterThan(no.x + no.width + 40);

    await expect(confirm.prose).toHaveCount(0);
    await expect(item.root).not.toContainText(BEFORE);
  });

  test('says plainly why Pilot asks, on every ground the record holds, never in the grants table’s terms', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Why'), members: [me.handle!] });
    const grounds = [
      ['auto-pilot-off', 'Auto pilot off', 'Pilot asks because auto pilot is off; under auto pilot it would go ahead'],
      ['rider', 'Auto pilot off: other commits go too', "The push carries commits that are not this project's; under auto pilot it would go ahead"],
      ['irreversible', 'Always asks: cannot be undone', 'Pilot asks for an act that cannot be undone, even under auto pilot'],
      ['product-hold', 'Always asks: you held this back', 'You held this back; Pilot asks even under auto pilot'],
      ['self-approval', 'Always asks: overrules a check', 'Going ahead would overrule a hold or a failed check; Pilot asks even under auto pilot'],
      ['standing-grant', 'Always asks: a lasting permission', 'The permission would outlast the project or reach past it; Pilot asks even under auto pilot'],
    ] as const;
    const placed = [];
    for (const [code] of grounds) {
      const text = `\`\`\`decision id=C1\ntype: confirmation\nproposal: Push the release\nbecause: ${code}\n\`\`\`\n`;
      placed.push(await projects.place(id, { kind: 'confirmation', title: `Ship on ${code}?`, text }));
    }
    await timeline.open(id);

    for (const [index, [, label, tooltip]] of grounds.entries()) {
      const { why } = timeline.item(placed[index]);
      await expect(why).toHaveText(label);
      await expect(why).toHaveAttribute('title', tooltip);
    }
  });

  test('unfolds its prose under Details, on the left and never underlined, which Less folds again; with no prose it has no Details', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Details'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: CONFIRMATION });
    const bare = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.3?', text: BLOCK });
    await timeline.open(id);
    const { confirm } = timeline.item(confirmation);

    await expect(confirm.details).toHaveText('Details');
    await expect(confirm.details).toHaveAttribute('aria-expanded', 'false');
    const underline = (element: Element) => getComputedStyle(element).textDecorationLine;
    const left = async () => (await confirm.details.boundingBox())!.x - (await confirm.proposal.boundingBox())!.x;
    expect(Math.abs(await left())).toBeLessThan(1);
    await confirm.details.hover();
    expect(await confirm.details.evaluate(underline)).toBe('none');
    await confirm.details.click();
    await expect(confirm.details).toHaveText('Less');
    expect(Math.abs(await left())).toBeLessThan(1);
    expect(await confirm.details.evaluate(underline)).toBe('none');
    await expect(confirm.prose).toContainText(BEFORE);
    await expect(confirm.prose).toContainText(AFTER);
    // The words before the block and after it stand a paragraph apart, as a document's parts do.
    const parts = confirm.prose.locator(':scope > .prose');
    await expect(parts).toHaveText([BEFORE, AFTER]);
    const fontSize = await parts.nth(1).evaluate((part) => parseFloat(getComputedStyle(part).fontSize));
    expect(await parts.nth(1).evaluate((part) => parseFloat(getComputedStyle(part).marginTop))).toBeCloseTo(0.7 * fontSize, 1);
    await confirm.details.click();
    await expect(confirm.prose).toHaveCount(0);

    await expect(timeline.item(bare).confirm.details).toHaveCount(0);
  });

  test('chooses Yes on its button, a soft one then, and saves it on Send, reading Yes in its block, not boxed, while it saves, Yes and No standing disabled, and its line leads with a check in the primary', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Yes'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: CONFIRMATION });
    await timeline.open(id);
    const item = timeline.item(confirmation);
    const { confirm } = item;

    await confirm.yes.click();
    // A press only chooses: nothing of it is on the record.
    await expect(confirm.yes).toHaveClass('btn btn-soft');
    await expect(confirm.yes).toHaveAttribute('data-chosen', 'true');
    await expect(confirm.no).toHaveClass('btn');
    await expect(item.root).toHaveAttribute('data-state', 'open');
    expect((await projects.block(id, confirmation)).answer).toBeNull();

    const restore = await slowNetwork(page, 1_000);
    await confirm.answerSend.click();
    const said = item.block.said.locator('.said');
    await expect(said).toHaveText('Yes');
    // Read at once, while the write is on its way.
    expect(await said.getAttribute('class')).not.toMatch(/\bboxed\b/);
    // The buttons stand through the save, for the Send's spinner (busy-press.spec.ts).
    await expect(confirm.yes).toBeDisabled();
    await expect(confirm.yes).toHaveAttribute('data-chosen', 'true');
    await expect(confirm.no).toBeDisabled();
    await expect(confirm.answerSend).toBeDisabled();
    await expect(confirm.proposal).toHaveText('Push the release to production');
    await restore();

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineKind).toHaveAttribute('title', 'Yes');
    await expect(item.lineKind.locator('svg')).toHaveClass(/\blucide-check\b/);
    // In the primary, as every other done line's kind icon: no class of its own tints it.
    await expect(item.lineKind).toHaveClass('kind-icon');
    await expect(item.lineKind).toHaveCSS('color', await cssColour(page, 'hsl(var(--primary))'));
    await expect(item.said).toHaveCount(0);
    expect(await projects.block(id, confirmation)).toMatchObject({ answer: 'Yes', note: null, via: 'app', by: { handle: me.handle } });
  });

  test('opens a reason console on No, which is chosen while it stands open; Enter breaks the line, Ctrl+Enter, the block’s Send, sends No with the reason, and the line leads with a cross in the primary and the reason', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('No'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: CONFIRMATION });
    await timeline.open(id);
    const item = timeline.item(confirmation);
    const { confirm } = item;

    await confirm.no.click();
    await expect(confirm.no).toHaveAttribute('aria-expanded', 'true');
    await expect(confirm.console).toBeVisible();
    await expect(confirm.field).toBeFocused();
    await expect(confirm.field).toHaveAttribute('placeholder', 'No: why not? (you may leave it empty)');
    // No is chosen, a soft button; its console has no Send of its own, and the reason may stay empty.
    await expect(confirm.no).toHaveClass('btn btn-soft');
    await expect(confirm.yes).toHaveClass('btn');
    await expect(confirm.send).toHaveCount(0);
    await expect(confirm.answerSend).toBeEnabled();

    await confirm.field.pressSequentially('Wait for the tests,');
    await confirm.field.press('Enter');
    await confirm.field.pressSequentially('they run tonight.');
    await confirm.field.press('Control+Enter');

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineKind).toHaveAttribute('title', 'No');
    await expect(item.lineKind.locator('svg')).toHaveClass(/\blucide-x\b/);
    // A No is no cancel and no error: the cross in the primary, neither grey nor red.
    await expect(item.lineKind).toHaveClass('kind-icon');
    await expect(item.lineKind).toHaveCSS('color', await cssColour(page, 'hsl(var(--primary))'));
    await expect(item.said).toHaveText('Wait for the tests, they run tonight.');
    await expect(item.note.locator('svg')).toHaveClass(/\blucide-sticky-note\b/);
    expect(await projects.block(id, confirmation)).toMatchObject({ answer: 'No', note: 'Wait for the tests,\nthey run tonight.' });
  });

  test('closes the reason console on Esc and the cross, which give the choice back, keeping the reason after a reload, and sends No with none once it is cleared', async ({
    page,
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Empty'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: CONFIRMATION });
    await timeline.open(id);
    const item = timeline.item(confirmation);
    const { confirm } = item;
    const kept = () => page.evaluate((key) => JSON.parse(localStorage.getItem(key) ?? '{}') as Record<string, string>, UNSENT_KEY);

    await confirm.no.click();
    await confirm.field.fill('Not now');
    await confirm.field.press('Escape');
    await expect(confirm.console).toHaveCount(0);
    // Nothing was chosen before the No: nothing is again, and Send waits.
    await expect(confirm.no).toHaveClass('btn');
    await expect(confirm.answerSend).toBeDisabled();
    await confirm.no.click();
    await expect(confirm.field).toHaveValue('Not now');
    await confirm.cancel.click();
    await expect(confirm.console).toHaveCount(0);
    expect(await kept()).toMatchObject({ [`${confirmation}/C1/no`]: 'Not now' });

    await timeline.open(id);
    await confirm.no.click();
    await expect(confirm.field).toHaveValue('Not now');
    await confirm.field.fill('');
    await confirm.answerSend.click();

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineKind).toHaveAttribute('title', 'No');
    await expect(item.said).toHaveCount(0);
    expect(await projects.block(id, confirmation)).toMatchObject({ answer: 'No', note: null });
    expect(await kept()).not.toHaveProperty(`${confirmation}/C1/no`);
    expect(await kept()).not.toHaveProperty(`${confirmation}/C1/choice`);
  });

  test('finds its choice again after a reload, the No with its console open and its reason; the cross gives back the Yes chosen before it, which Send then saves', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Reloaded'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: CONFIRMATION });
    await timeline.open(id);
    const item = timeline.item(confirmation);
    const { confirm } = item;

    await confirm.yes.click();
    await confirm.no.click();
    await expect(confirm.no).toHaveAttribute('data-chosen', 'true');
    await expect(confirm.yes).toHaveAttribute('data-chosen', 'false');
    await confirm.field.fill('Wait for the tests.');

    await timeline.open(id);
    await expect(confirm.field).toHaveValue('Wait for the tests.');
    await expect(confirm.field).not.toBeFocused();
    await expect(confirm.no).toHaveClass('btn btn-soft');
    await confirm.cancel.click();
    await expect(confirm.console).toHaveCount(0);
    await expect(confirm.yes).toHaveClass('btn btn-soft');
    await expect(confirm.no).toHaveClass('btn');
    await expect(item.root).toHaveAttribute('data-state', 'open');
    expect((await projects.block(id, confirmation)).answer).toBeNull();

    await timeline.open(id);
    await expect(confirm.yes).toHaveAttribute('data-chosen', 'true');
    await confirm.answerSend.click();
    await expect(item.lineKind).toHaveAttribute('title', 'Yes');
    expect(await projects.block(id, confirmation)).toMatchObject({ answer: 'Yes', note: null, by: { handle: me.handle } });
  });

  test('holds a No’s reason typed in the item’s tab on the timeline under it too, whose Send sends the No with it once the tab closes', async ({
    people,
    projects,
    timeline,
    overlay,
    docTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Under its tab'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: CONFIRMATION });
    // At the item's address the timeline stands under its tab: the block is drawn twice.
    await overlay.open(id, confirmation);
    const tab = overlay.blockAt('C1');
    await tab.no.click();
    await tab.noField.fill('Wait for the tests.');

    await docTabs.document(confirmation).close.click();
    await expect(overlay.root).toHaveCount(0);
    const item = timeline.item(confirmation);
    await expect(item.confirm.no).toHaveAttribute('data-chosen', 'true');
    await expect(item.confirm.field).toHaveValue('Wait for the tests.');
    await item.confirm.answerSend.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
    expect(await projects.block(id, confirmation)).toMatchObject({ answer: 'No', note: 'Wait for the tests.', by: { handle: me.handle } });
  });

  test('answered by Pilot reads its answer and its note in its block, closed, and opens to Yes and No for the person’s', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Pilot’s'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: PILOTS });
    await timeline.open(id);
    const item = timeline.item(confirmation);
    const { confirm } = item;

    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(confirm.proposal).toHaveText('Push the release to production');
    await expect(item.block.who.locator('.avatar')).toHaveAttribute('title', 'Pilot');
    await expect(item.block.said.locator('.said')).toHaveText('Yes');
    await expect(item.block.said.locator('.said')).not.toHaveClass(/\bboxed\b/);
    await expect(item.block.note).toHaveText('The checks are green.');
    await expect(confirm.yes).toHaveCount(0);

    await item.block.toggle.click();
    await expect(confirm.yes).toBeEnabled();
    await expect(confirm.answerSend).toBeDisabled();
    await confirm.no.click();
    await confirm.field.fill('Hold it');
    await confirm.answerSend.click();
    await expect(item.lineKind).toHaveAttribute('title', 'No');
    expect(await projects.block(id, confirmation)).toMatchObject({ answer: 'No', note: 'Hold it', by: { handle: me.handle } });
  });
});

test.describe('A done confirmation', () => {
  test('reads its answer alone, and opens on its chevron to its proposal, Yes and No standing and taking nothing, and its reason, then closes again', async ({
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Done'), members: [me.handle!] });
    const agreed = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: CONFIRMATION });
    const refused = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.3?', text: CONFIRMATION });
    await projects.answer(agreed, 'C1', 'Yes');
    await projects.answer(refused, 'C1', 'No', 'Wait for the tests.');

    for (const [confirmation, said, reason] of [
      [agreed, 'Yes', null],
      [refused, 'No', 'Wait for the tests.'],
    ] as const) {
      await timeline.open(id);
      await timeline.item(confirmation).lineTitle.click();
      const block = overlay.blockAt('C1');
      const reads = async () => {
        await expect(block.said.locator('.said')).toHaveText(said);
        await expect(block.said.locator('.said')).not.toHaveClass(/\bboxed\b/);
        if (reason === null) await expect(block.note).toHaveCount(0);
        else await expect(block.note).toHaveText(reason);
      };
      await expect(overlay.doneChip).toHaveText('Done');
      await expect(block.kind).toHaveText('Confirm');
      await expect(block.root).toHaveAttribute('data-closed', 'true');
      await reads();
      await expect(block.proposal).toHaveCount(0);
      await expect(block.yes).toHaveCount(0);
      await expect(block.no).toHaveCount(0);
      await expect(block.toggle).toHaveAttribute('aria-expanded', 'false');
      await expect(block.toggle).toHaveAttribute('aria-label', 'Show expansion list');

      await block.toggle.click();
      await expect(block.root).toHaveAttribute('data-closed', 'false');
      await expect(block.toggle).toHaveAttribute('aria-expanded', 'true');
      await expect(block.toggle).toHaveAttribute('aria-label', 'Show only the answer');
      await expect(block.proposal).toHaveText('Push the release to production');
      await reads();
      await expect(block.yes).toBeDisabled();
      await expect(block.no).toBeDisabled();
      await expect(block.root.getByTestId('timeline.confirm.console')).toHaveCount(0);

      await block.toggle.click();
      await expect(block.root).toHaveAttribute('data-closed', 'true');
      await reads();
      await expect(block.proposal).toHaveCount(0);
      await expect(block.yes).toHaveCount(0);
    }
  });
});

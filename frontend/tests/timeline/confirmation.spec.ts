/**
 * A confirmation (F22): a compact yellow card, its reason line with the ground as tooltip (F22.1),
 * the title and the proposal beside a check and a cross, no Other (F22.2, F17.3); No opening a
 * console whose reason may stay empty and is the note (F22.3), in the growing field kept until sent
 * (F115, F110, F133); Details / Less unfolding the prose (F22.4); and its done line led by a green
 * check or a red cross with the reason (F22.5).
 */

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
  test('is a compact yellow card: its reason line, the title and the proposal beside a check and a cross, no Other, the prose folded', async ({
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
    await expect(confirm.root).toHaveAttribute('data-block-id', 'C1');
    await expect(confirm.yes).toHaveAttribute('title', 'Yes: Push the release to production');
    await expect(confirm.no).toHaveAttribute('title', 'No, and say why');
    await expect(item.block.root).toHaveCount(0);
    await expect(item.root.getByTestId('timeline.block.other')).toHaveCount(0);

    // The proposal and the check and the cross share a row.
    const yes = (await confirm.yes.boundingBox())!;
    const text = (await confirm.proposal.boundingBox())!;
    expect(yes.x).toBeGreaterThan(text.x + text.width - 1);
    expect(yes.y).toBeLessThan(text.y + text.height);

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

  test('unfolds its prose under Details, which Less folds again; with no prose it has no Details', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Details'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: CONFIRMATION });
    const bare = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.3?', text: BLOCK });
    await timeline.open(id);
    const { confirm } = timeline.item(confirmation);

    await expect(confirm.details).toHaveText('Details');
    await expect(confirm.details).toHaveAttribute('aria-expanded', 'false');
    await confirm.details.click();
    await expect(confirm.details).toHaveText('Less');
    await expect(confirm.prose).toContainText(BEFORE);
    await expect(confirm.prose).toContainText(AFTER);
    await confirm.details.click();
    await expect(confirm.prose).toHaveCount(0);

    await expect(timeline.item(bare).confirm.details).toHaveCount(0);
  });

  test('saves Yes on the check, which stays coloured while it saves, and its line leads with a green check', async ({
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

    const restore = await slowNetwork(page, 1_000);
    await confirm.yes.click();
    await expect(confirm.yes).toHaveClass(/\bchosen\b/);
    await expect(confirm.yes).toBeDisabled();
    await expect(confirm.no).toBeDisabled();
    await restore();

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineKind).toHaveClass(/\byes\b/);
    await expect(item.lineKind).toHaveAttribute('title', 'Yes');
    await expect(item.lineKind.locator('svg')).toHaveClass(/\blucide-check\b/);
    expect(await item.lineKind.evaluate((element) => getComputedStyle(element).color)).not.toBe(
      await item.lineTitle.evaluate((element) => getComputedStyle(element).color),
    );
    await expect(item.said).toHaveCount(0);
    expect(await projects.block(id, confirmation)).toMatchObject({ answer: 'Yes', note: null, via: 'app', by: { handle: me.handle } });
  });

  test('opens a reason console on the cross; Enter breaks the line, Ctrl+Enter sends No with the reason, and the line leads with a red cross and the reason', async ({
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
    await expect(confirm.send).toHaveAttribute('title', 'Send No (Ctrl+Enter)');
    await expect(confirm.send).toBeEnabled();

    await confirm.field.pressSequentially('Wait for the tests,');
    await confirm.field.press('Enter');
    await confirm.field.pressSequentially('they run tonight.');
    await confirm.field.press('Control+Enter');

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineKind).toHaveClass(/\bno\b/);
    await expect(item.lineKind.locator('svg')).toHaveClass(/\blucide-x\b/);
    await expect(item.said).toHaveText('Wait for the tests, they run tonight.');
    await expect(item.note.locator('svg')).toHaveClass(/\blucide-sticky-note\b/);
    expect(await projects.block(id, confirmation)).toMatchObject({ answer: 'No', note: 'Wait for the tests,\nthey run tonight.' });
  });

  test('closes the reason console on Esc and the cross, keeping the reason after a reload, and sends No with none once it is cleared', async ({
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
    await confirm.no.click();
    await expect(confirm.field).toHaveValue('Not now');
    await confirm.cancel.click();
    await expect(confirm.console).toHaveCount(0);
    expect(await kept()).toMatchObject({ [`${confirmation}/C1/no`]: 'Not now' });

    await timeline.open(id);
    await confirm.no.click();
    await expect(confirm.field).toHaveValue('Not now');
    await confirm.field.fill('');
    await confirm.send.click();

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineKind).toHaveClass(/\bno\b/);
    await expect(item.said).toHaveCount(0);
    expect(await projects.block(id, confirmation)).toMatchObject({ answer: 'No', note: null });
    expect(await kept()).not.toHaveProperty(`${confirmation}/C1/no`);
  });

  test('answered by Pilot shows its answer coloured and its note, and takes the person’s', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Pilot’s'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: PILOTS });
    await timeline.open(id);
    const item = timeline.item(confirmation);
    const { confirm } = item;

    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(confirm.yes).toHaveClass(/\bchosen\b/);
    await expect(confirm.no).not.toHaveClass(/\bchosen\b/);
    await expect(confirm.root.getByTestId('timeline.block.note')).toHaveText('The checks are green.');

    await confirm.no.click();
    await confirm.field.fill('Hold it');
    await confirm.send.click();
    await expect(item.lineKind).toHaveClass(/\bno\b/);
    expect(await projects.block(id, confirmation)).toMatchObject({ answer: 'No', note: 'Hold it', by: { handle: me.handle } });
  });
});

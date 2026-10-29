/**
 * Auto pilot's switch turning on while confirmations it would take are open (F4.2): it asks first
 * in a dialog; Yes answers each, a confirmation item and a confirmation block in a document alike,
 * as the person's Yes through auto pilot; No, Esc or a click beside the dialog turns auto pilot on
 * and leaves them open, and turning it off and on again asks again; with none open, or only ones
 * that ask under auto pilot too, it asks nothing.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { slowNetwork } from '../support/network';

const confirming = (because: string) =>
  `\`\`\`decision id=C1\ntype: confirmation\nproposal: Push the release to production\nbecause: ${because}\n\`\`\`\n`;
const RELEASE = [
  'The tag is cut and the notes are written.\n',
  '```decision id=C1\ntype: confirmation\nproposal: Tag the release\nbecause: rider\n```\n',
  '```question id=Q1\n```\n',
].join('\n');

test.describe('Auto pilot turning on', () => {
  test('asks nothing with no open confirmation it would take, those that ask under auto pilot too left open', async ({
    people,
    projects,
    projectHead,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('None'), members: [me.handle!] });
    const kept = [
      await projects.place(id, { kind: 'confirmation', title: 'Drop the table?', text: confirming('irreversible') }),
      await projects.place(id, { kind: 'confirmation', title: 'Grant the deploy key?', text: confirming('standing-grant') }),
    ];
    await timeline.open(id);
    expect((await projects.head(id)).autopilot_may_take).toBe(0);

    await projectHead.autopilot.click();
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
    await expect(projectHead.autopilotDialog.root).toHaveCount(0);
    for (const confirmation of kept) {
      await expect(timeline.item(confirmation).confirm.yes).toBeEnabled();
      expect((await projects.block(id, confirmation)).answer).toBeNull();
    }
  });

  test('asks first; Yes answers each it would take as the person’s Yes through auto pilot, in a document too', async ({
    people,
    projects,
    projectHead,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Yes'), members: [me.handle!] });
    const off = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: confirming('auto-pilot-off') });
    const rider = await projects.place(id, { kind: 'confirmation', title: 'Push with the fix?', text: confirming('rider') });
    const kept = await projects.place(id, { kind: 'confirmation', title: 'Drop the table?', text: confirming('irreversible') });
    const release = await projects.place(id, { kind: 'document', title: 'The release', text: RELEASE });
    await timeline.open(id);
    const dialog = projectHead.autopilotDialog;

    await projectHead.autopilot.click();
    await expect(dialog.root).toBeVisible();
    await expect(dialog.title).toHaveText('Answer what auto pilot would take?');
    await expect(dialog.lines).toHaveText([
      '3 open confirmations ask only because auto pilot is off.',
      'Yes answers them Yes for you, and Pilot goes ahead.',
      'No leaves them open for you to answer.',
    ]);
    await expect(dialog.note).toHaveText('Auto pilot turns on either way.');
    await expect(dialog.no).toHaveText('No');
    await expect(dialog.yes).toHaveText('Yes');
    await expect(dialog.no).toBeFocused();
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');

    await dialog.yes.click();
    await expect(dialog.root).toHaveCount(0);
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
    await expect(projectHead.autopilot).toBeFocused();
    for (const confirmation of [off, rider]) {
      const item = timeline.item(confirmation);
      await expect(item.root).toHaveAttribute('data-state', 'done');
      await expect(item.lineKind).toHaveClass(/\byes\b/);
      expect(await projects.block(id, confirmation)).toMatchObject({ answer: 'Yes', via: 'autopilot', by: { handle: me.handle } });
    }
    await expect(timeline.item(release).blockAt('C1').answered).toBeVisible();
    const blocks = (await projects.item(id, release)).body!.flatMap((part) => (part.type === 'block' ? [part.block] : []));
    expect(blocks.find((block) => block.id === 'C1')).toMatchObject({ answer: 'Yes', via: 'autopilot', by: { handle: me.handle } });
    expect(blocks.find((block) => block.id === 'Q1')!.answer).toBeNull();
    await expect(timeline.item(kept).confirm.yes).toBeEnabled();
    expect((await projects.block(id, kept)).answer).toBeNull();
    expect(await projects.head(id)).toMatchObject({ autopilot: true, autopilot_may_take: 0 });
  });

  test('No, Esc and a click beside the dialog each turn it on and leave them open; it asks again each time it turns on', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('No'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: confirming('auto-pilot-off') });
    await timeline.open(id);
    const dialog = projectHead.autopilotDialog;
    const leaves = async () => {
      await expect(dialog.root).toHaveCount(0);
      await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
      await expect(timeline.item(confirmation).confirm.yes).toBeEnabled();
      expect(await projects.head(id)).toMatchObject({ autopilot: true, autopilot_may_take: 1 });
      expect((await projects.block(id, confirmation)).answer).toBeNull();
    };
    const turnOff = async () => {
      await projectHead.autopilot.click();
      await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
      await expect(dialog.root).toHaveCount(0);
    };

    await projectHead.autopilot.click();
    await expect(dialog.lines).toHaveText([
      'One open confirmation asks only because auto pilot is off.',
      'Yes answers it Yes for you, and Pilot goes ahead.',
      'No leaves it open for you to answer.',
    ]);
    await dialog.no.click();
    await leaves();

    await turnOff();
    await projectHead.autopilot.click();
    await expect(dialog.root).toBeVisible();
    await page.keyboard.press('Escape');
    await leaves();

    await turnOff();
    await projectHead.autopilot.click();
    await expect(dialog.root).toBeVisible();
    await dialog.backdrop.click({ position: { x: 5, y: 5 } });
    await leaves();
  });

  test('holds while auto pilot turns on: its answers disabled, and Esc sends nothing more', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Pending'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: confirming('auto-pilot-off') });
    await timeline.open(id);
    const dialog = projectHead.autopilotDialog;

    await projectHead.autopilot.click();
    const restore = await slowNetwork(page, 1_000);
    await dialog.yes.click();
    await expect(dialog.yes).toBeDisabled();
    await expect(dialog.no).toBeDisabled();
    await page.keyboard.press('Escape');
    await expect(dialog.root).toBeVisible();
    await restore();

    await expect(dialog.root).toHaveCount(0);
    await expect(timeline.item(confirmation).root).toHaveAttribute('data-state', 'done');
    expect((await projects.block(id, confirmation)).via).toBe('autopilot');
  });

  test('goes once another session turns auto pilot on or finishes the project, and stays gone after a Reopen', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Elsewhere'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: confirming('auto-pilot-off') });
    await timeline.open(id);
    const dialog = projectHead.autopilotDialog;

    await projectHead.autopilot.click();
    await expect(dialog.root).toBeVisible();
    await projects.transition(id, 'autopilot_on');
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
    await expect(dialog.root).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(timeline.item(confirmation).confirm.yes).toBeEnabled();
    expect(await projects.head(id)).toMatchObject({ autopilot: true, autopilot_may_take: 1 });

    await projectHead.autopilot.click();
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
    await projectHead.autopilot.click();
    await expect(dialog.root).toBeVisible();
    await projects.transition(id, 'finished');
    await expect(projectHead.finished).toBeVisible();
    await expect(dialog.root).toHaveCount(0);
    await projects.transition(id, 'reopened');
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
    await expect(dialog.root).toHaveCount(0);
  });

  test('goes once another session archives the project, and stays gone after a Bring back', async ({
    people,
    projects,
    projectHead,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Archived'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: confirming('auto-pilot-off') });
    await timeline.open(id);
    const dialog = projectHead.autopilotDialog;

    await projectHead.autopilot.click();
    await expect(dialog.root).toBeVisible();
    await projects.transition(id, 'archived');
    await expect(projectHead.archived).toBeVisible();
    await expect(dialog.root).toHaveCount(0);
    await projects.transition(id, 'brought_back');
    await expect(projectHead.archived).toHaveCount(0);
    await expect(dialog.root).toHaveCount(0);
    expect(await projects.head(id)).toMatchObject({ autopilot: false, autopilot_may_take: 1 });
    await expect(timeline.item(confirmation).confirm.yes).toBeEnabled();
  });
});

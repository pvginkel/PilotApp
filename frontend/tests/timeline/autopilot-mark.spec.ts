/**
 * The auto pilot mark (F4.4): on an open confirmation the switch would answer while the project's
 * auto pilot is off, the mockup's icon in the time's grey at a kind icon's size, its hover saying
 * auto pilot will handle it; in a confirmation card's head after the time and its dot, before the
 * why-label; in a confirmation block's head beside its kind, in a document inline and in the
 * overlay; on a document's card a grey chip beside the counts, the mark and "<n> auto pilot may
 * take". An answer hides it, and so does auto pilot turned on; a confirmation that asks under auto
 * pilot too, or of an item closed unanswered, carries none.
 */

import type { Locator } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

const HANDLES_THIS = 'Auto pilot will handle this for you';
const HANDLES_THESE = 'Auto pilot will handle these for you';

const confirming = (because: string, id = 'C1') =>
  `\`\`\`decision id=${id}\ntype: confirmation\nproposal: Push the release to production\nbecause: ${because}\n\`\`\`\n`;
const document = (...becauses: string[]) =>
  ['The tag is cut and the notes are written.\n', ...becauses.map((because, index) => confirming(because, `C${index + 1}`)), '```question id=Q1\n```\n'].join(
    '\n',
  );
const words = Array.from({ length: 160 }, (_, index) => `word${index}`).join(' ');
const long = (...becauses: string[]) => `${words}\n\n${document(...becauses)}`;

/** The mark's icon: Pilot's mark, masked by a cut-out its own mask defines, and the filled bolt. */
async function expectTheIcon(mark: Locator) {
  const svg = mark.locator('svg');
  await expect(svg).toHaveCount(1);
  expect(
    await svg.evaluate((element) => {
      const masked = element.querySelector('g[mask]')!;
      const id = /^url\(#(.+)\)$/.exec(masked.getAttribute('mask')!)![1];
      return {
        masks: element.ownerDocument.querySelectorAll(`mask[id="${id}"]`).length,
        inside: element.querySelector(`mask[id="${id}"]`) !== null,
        paths: masked.querySelectorAll('path').length,
        bolt: element.querySelector(':scope > path')!.getAttribute('fill'),
      };
    }),
  ).toEqual({ masks: 1, inside: true, paths: 3, bolt: 'currentColor' });
}

test.describe('The auto pilot mark', () => {
  test('stands in a confirmation card’s head after the time and its dot, before the why-label, in the time’s grey', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Card mark'), members: [me.handle!] });
    const off = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: confirming('auto-pilot-off') });
    const rider = await projects.place(id, { kind: 'confirmation', title: 'Push with the fix?', text: confirming('rider') });
    const kept = [
      await projects.place(id, { kind: 'confirmation', title: 'Drop the table?', text: confirming('irreversible') }),
      await projects.place(id, { kind: 'confirmation', title: 'Grant the deploy key?', text: confirming('standing-grant') }),
    ];
    await timeline.open(id);

    for (const confirmation of [off, rider]) {
      const item = timeline.item(confirmation);
      const mark = item.autopilotMark;
      await expect(mark).toBeVisible();
      await expect(mark).toHaveAttribute('title', HANDLES_THIS);
      await expectTheIcon(mark);
      const style = await mark.evaluate((element) => {
        const { cursor, color } = getComputedStyle(element);
        const icon = element.querySelector('svg')!.getBoundingClientRect();
        return { cursor, color, width: icon.width, height: icon.height };
      });
      expect(style).toMatchObject({ cursor: 'help', width: 13, height: 13 });
      expect(style.color).toBe(await item.time.evaluate((element) => getComputedStyle(element).color));

      const [time, at, why] = await Promise.all([item.time, mark, item.why].map(async (part) => (await part.boundingBox())!));
      expect(at.x).toBeGreaterThan(time.x + time.width);
      expect(why.x).toBeGreaterThan(at.x + at.width);
      const seps = item.head.locator('.sep');
      await expect(seps).toHaveCount(3);
      expect(await seps.evaluateAll((all) => all.map((sep) => getComputedStyle(sep).opacity))).toEqual(['0.75', '0.75', '0.75']);
    }
    for (const confirmation of kept) {
      const item = timeline.item(confirmation);
      await expect(item.why).toBeVisible();
      await expect(item.autopilotMark).toHaveCount(0);
      await expect(item.head.locator('.sep')).toHaveCount(2);
    }
  });

  test('stands in a confirmation block’s head beside its kind, in a document inline and in the overlay', async ({
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Block mark'), members: [me.handle!] });
    const release = await projects.place(id, { kind: 'document', title: 'The release', text: document('auto-pilot-off', 'irreversible') });
    await timeline.open(id);
    const item = timeline.item(release);

    const marked = item.blockAt('C1');
    await expect(marked.autopilotMark).toBeVisible();
    await expect(marked.autopilotMark).toHaveAttribute('title', HANDLES_THIS);
    await expectTheIcon(marked.autopilotMark);
    const [kind, mark] = await Promise.all([marked.kind, marked.autopilotMark].map(async (part) => (await part.boundingBox())!));
    expect(mark.x).toBeGreaterThan(kind.x + kind.width);
    expect(mark.x - (kind.x + kind.width)).toBeLessThan(12);
    await expect(item.blockAt('C2').autopilotMark).toHaveCount(0);
    await expect(item.blockAt('Q1').autopilotMark).toHaveCount(0);
    await expect(item.autopilotMark).toHaveCount(0);

    await overlay.open(id, release);
    await expect(overlay.blockAt('C1').autopilotMark).toBeVisible();
    await expect(overlay.blockAt('C1').autopilotMark).toHaveAttribute('title', HANDLES_THIS);
    await expect(overlay.blockAt('C2').autopilotMark).toHaveCount(0);
  });

  test('stands on a document’s card as a grey chip beside the counts, its count and its hover', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Chip'), members: [me.handle!] });
    const two = await projects.place(id, { kind: 'document', title: 'Two to take', text: long('auto-pilot-off', 'rider', 'irreversible') });
    const one = await projects.place(id, { kind: 'document', title: 'One to take', text: long('rider') });
    const none = await projects.place(id, { kind: 'document', title: 'None to take', text: long('irreversible') });
    await timeline.open(id);

    const { card } = timeline.item(two);
    await expect(card.autopilotChip).toHaveText('2 auto pilot may take');
    await expect(card.autopilotChip).toHaveAttribute('title', HANDLES_THESE);
    await expect(card.autopilotChip).toHaveClass(/\bchip\b/);
    await expectTheIcon(card.autopilotChip);
    expect(await card.autopilotChip.evaluate((element) => getComputedStyle(element).cursor)).toBe('help');
    expect(await card.autopilotChip.evaluate((element) => element.previousElementSibling?.getAttribute('data-testid'))).toBe(
      'timeline.item.count',
    );
    await expect(card.counts).toHaveText(['3 decisions', '1 question']);

    await expect(timeline.item(one).card.autopilotChip).toHaveText('1 auto pilot may take');
    await expect(timeline.item(one).card.autopilotChip).toHaveAttribute('title', HANDLES_THIS);
    await expect(timeline.item(none).card.counts).toHaveText(['1 decision', '1 question']);
    await expect(timeline.item(none).card.autopilotChip).toHaveCount(0);
  });

  test('goes once the confirmation is answered or auto pilot is on, and stands again once it is off', async ({
    people,
    projects,
    projectHead,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Goes'), members: [me.handle!] });
    const confirmation = await projects.place(id, { kind: 'confirmation', title: 'Ship 1.2?', text: confirming('auto-pilot-off') });
    const inline = await projects.place(id, { kind: 'document', title: 'The release', text: document('auto-pilot-off') });
    const card = await projects.place(id, { kind: 'document', title: 'The long release', text: long('auto-pilot-off', 'rider') });
    await timeline.open(id);
    const chip = timeline.item(card).card.autopilotChip;
    await expect(chip).toHaveText('2 auto pilot may take');

    await projects.answer(card, 'C1', 'Yes');
    await expect(chip).toHaveText('1 auto pilot may take');
    await expect(chip).toHaveAttribute('title', HANDLES_THIS);

    const block = timeline.item(inline).blockAt('C1');
    await expect(block.autopilotMark).toBeVisible();
    await block.yes.click();
    await expect(block.answered).toBeVisible();
    await expect(block.autopilotMark).toHaveCount(0);

    const marked = timeline.item(confirmation).autopilotMark;
    await expect(marked).toBeVisible();
    await projects.transition(id, 'autopilot_on');
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
    await expect(marked).toHaveCount(0);
    await expect(chip).toHaveCount(0);
    await expect(timeline.item(confirmation).confirm.yes).toBeEnabled();

    await projects.transition(id, 'autopilot_off');
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'false');
    await expect(marked).toBeVisible();
    await expect(chip).toHaveText('1 auto pilot may take');
  });

  test('stands on no confirmation of an item closed unanswered: a document Finish closed reads in the overlay without it', async ({
    people,
    projects,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Closed'), members: [me.handle!] });
    const release = await projects.place(id, { kind: 'document', title: 'The release', text: document('auto-pilot-off') });
    await projects.transition(id, 'finished');

    await overlay.open(id, release);
    await expect(overlay.blockAt('C1').root).toBeVisible();
    expect((await projects.item(id, release)).done).not.toBeNull();
    await expect(overlay.blockAt('C1').autopilotMark).toHaveCount(0);
  });
});

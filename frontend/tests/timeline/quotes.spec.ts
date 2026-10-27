/**
 * Quote tags (F38.3, F39.3; `database.md` decision 62) as chips on every screen that renders
 * Markdown — an item on the timeline, a confirmation's details, a document's overlay, the handbook,
 * the project document, a Markdown attachment — each going to what it quotes: an item to its
 * address, a block to its own, opening the overlay where its document is a card, and a path to its
 * file's overlay, the handbook's, the project document's or an attachment's. Inside a code span or
 * a fence, or behind a backslash escape, a tag shows as written, as does a tag naming a path that is
 * no quote.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { handbookAddress, projectDocumentAddress } from '../support/page-objects/overlay-page';
import { addressOf, attachmentAddress } from '../support/page-objects/timeline-page';

const WORDS = (count: number) => Array.from({ length: count }, (_, index) => `word${index}`).join(' ');
const DECISION = 'Which tent for the trip?\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const TENT = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const PITCH = '```question id=Q1\n```\n';
const CARD = `---\nsummary: Where we go and what we take.\n---\n\n${WORDS(200)}\n\n## Which tent?\n\n${TENT}\n## Where do we pitch?\n\n${PITCH}`;

const tag = (kind: 'item' | 'block', id: string, title: string) => `<quoted_${kind} id="${id}">${title}</quoted_${kind} id="${id}">`;
const pathTag = (path: string, title: string) => `<quoted_path path="${path}">${title}</quoted_path path="${path}">`;

test.describe('A quote', () => {
  test('on a timeline item is a chip: an item’s goes to the item, a block’s to the block, opening the overlay where its document is a card; in a code span or a fence, or behind a backslash escape, the tag shows as written', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Quotes'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    const card = await projects.place(id, { kind: 'document', title: 'The trip', text: CARD });
    const item = tag('item', decision, 'Which tent?');
    const block = tag('block', `${card}/D1`, 'The tent to take');
    const notice = await projects.place(id, {
      kind: 'notice',
      title: 'Quoted',
      text: `See ${item} and ${block}.\n\nIn a span: \`${item}\`\n\n\`\`\`\n${block}\n\`\`\`\n\nEscaped: \\${item}\n`,
    });
    await timeline.open(id);

    const text = timeline.item(notice).text;
    const chips = text.getByTestId('chat.quote');
    await expect(chips).toHaveText(['Which tent?', 'The tent to take']);
    await expect(chips.first()).toHaveAttribute('data-quote', `item ${decision}`);
    await expect(chips.last()).toHaveAttribute('data-quote', `block ${card}/D1`);
    await expect(text.locator('code')).toHaveText([item, block]);
    await expect(text.getByText('Escaped:')).toHaveText(`Escaped: ${item}`);
    await expect(text).not.toContainText('pilot-quote');

    await chips.first().click();
    await expect(page).toHaveURL(addressOf(id, decision));
    await expect(timeline.item(decision).root).toBeInViewport();

    await chips.last().click();
    await expect(page).toHaveURL(addressOf(id, card, 'D1'));
    await expect(overlay.root).toBeVisible();
    await expect(overlay.blockAt('D1').root).toBeVisible();
  });

  test('by a path is a chip opening the handbook’s, the project document’s or an attachment’s overlay; a path naming any other file shows as written', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Paths'), members: [me.handle!] });
    await projects.saveProjectDocument(id, 'handbook', '# Handbook\n\nHow the trip is planned.\n');
    await projects.saveProjectDocument(id, 'draft', '# The trip plan\n\nWhere we go.\n');
    await projects.endTurn(id);
    const sketches = await projects.place(id, { kind: 'notice', title: 'Sketches', text: 'The sketches are attached.\n' });
    const [notes] = await projects.attach(sketches, [
      { title: 'Tent notes', filename: 'tent-notes.md', content_type: 'text/markdown', content: '# Tent notes\n\nThe dome is lighter.\n' },
    ]);
    const { batch } = (await projects.item(id, sketches)).attachments[0]!;
    const unknown = [pathTag('notes.md', 'Notes'), pathTag('../handbook.md', 'Up')];
    const notice = await projects.place(id, {
      kind: 'notice',
      title: 'Read these',
      text: [
        pathTag('handbook.md', 'Handbook'),
        pathTag('project.md', 'The trip plan'),
        pathTag(`attachments/${batch}/tent-notes.md`, 'Tent notes'),
        ...unknown,
      ].join(' and '),
    });
    await timeline.open(id);

    const text = timeline.item(notice).text;
    const chips = text.getByTestId('chat.quote');
    await expect(chips).toHaveText(['Handbook', 'The trip plan', 'Tent notes']);
    await expect(chips.nth(2)).toHaveAttribute('data-quote', `path attachments/${batch}/tent-notes.md`);
    for (const written of unknown) await expect(text).toContainText(written);

    await chips.nth(0).click();
    await expect(page).toHaveURL(handbookAddress(id));
    await expect(overlay.role).toHaveText('Handbook');
    await page.keyboard.press('Escape');
    await expect(overlay.root).toHaveCount(0);

    await chips.nth(1).click();
    await expect(page).toHaveURL(projectDocumentAddress(id));
    await expect(overlay.role).toHaveText('Project document');
    await page.keyboard.press('Escape');
    await expect(overlay.root).toHaveCount(0);

    await chips.nth(2).click();
    await expect(page).toHaveURL(attachmentAddress(id, sketches, notes!));
    await expect(overlay.attachment.prose).toContainText('The dome is lighter.');
  });

  test('goes where it quotes from every screen that renders Markdown: a confirmation’s details, a document’s overlay, the handbook, the project document and a Markdown attachment', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Everywhere'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    const item = tag('item', decision, 'Which tent?');
    const confirmation = await projects.place(id, {
      kind: 'confirmation',
      title: 'Ship 1.2?',
      text: `The tag is cut, as ${item} asked.\n\n\`\`\`decision id=C1\ntype: confirmation\nproposal: Push the release\nbecause: auto-pilot-off\n\`\`\`\n`,
    });
    const card = await projects.place(id, { kind: 'document', title: 'The trip', text: CARD.replace('word0', `See ${item}.`) });
    await projects.saveProjectDocument(id, 'handbook', `# Handbook\n\nThe plan: ${pathTag('project.md', 'The trip plan')}\n`);
    await projects.saveProjectDocument(id, 'draft', `# The trip plan\n\nFirst ${tag('block', `${decision}/D1`, 'The tent')}.\n`);
    await projects.endTurn(id);
    const [notes] = await projects.attach(decision, [
      {
        title: 'Tent notes',
        filename: 'tent-notes.md',
        content_type: 'text/markdown',
        content: `# Tent notes\n\nAs ${pathTag('handbook.md', 'the handbook')} says.\n`,
      },
    ]);

    await timeline.open(id);
    const details = timeline.item(confirmation).confirm;
    await details.details.click();
    await details.prose.getByTestId('chat.quote').click();
    await expect(page).toHaveURL(addressOf(id, decision));

    await overlay.open(id, card);
    await overlay.document.getByTestId('chat.quote').click();
    await expect(page).toHaveURL(addressOf(id, decision));
    await expect(overlay.root).toHaveCount(0);

    await overlay.openProjectDocument(id, 'handbook');
    await overlay.document.getByTestId('chat.quote').click();
    await expect(page).toHaveURL(projectDocumentAddress(id));
    await expect(overlay.role).toHaveText('Project document');

    await overlay.document.getByTestId('chat.quote').click();
    await expect(page).toHaveURL(addressOf(id, decision, 'D1'));
    await expect(timeline.item(decision).block.root).toBeInViewport();

    await timeline.item(decision).attachment(notes!).click();
    await expect(page).toHaveURL(attachmentAddress(id, decision, notes!));
    await overlay.attachment.prose.getByTestId('chat.quote').click();
    await expect(page).toHaveURL(handbookAddress(id));
    await expect(overlay.role).toHaveText('Handbook');
  });
});

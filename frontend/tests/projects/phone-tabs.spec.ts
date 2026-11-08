/**
 * A project's screen on a phone (F98.3): tabs at the bottom, Timeline, Chat, Plan and Documents,
 * each its icon over its name, the one showing in the primary's tint, its icon on a pill; the
 * head's Discuss, Documents and Draft buttons gone, the tabs being them (F2.3). Chat carries the
 * unread dot (F43) and Documents its count (F37.3) on the icon's corner; Chat and Documents are the
 * side panel's tabs between the head and the tabs, without the panel's head (F38.1); Plan is the
 * plan popover's content as a page, its rows a thumb's height (F3.7). A draft's tabs are Chat, the
 * definition chat in the timeline's place with Create project at its end, Draft and Documents.
 * Every project opens on its Timeline, and a draft on its Chat, whatever panel the browser keeps for
 * it, which the phone neither reads nor changes. Discuss and *In the chat* show the Chat tab, a
 * draft's its Chat, a view taken off; an ask of the draft gone to shows the Draft tab at it.
 * Back (F98.5): leaving the Timeline is one entry, a change between the other tabs none, so Back
 * from any of them shows the Timeline and Back there leaves the project; switching projects is an
 * entry; a reload keeps the tab.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique, makeUniqueToken, waitForUiState } from '../support/helpers';
import { isOnTop } from '../support/page-objects/panel-page';
import type { PhoneTabsPage } from '../support/page-objects/phone-tabs-page';
import type { ProjectHeadPage } from '../support/page-objects/project-head-page';
import { projectAddress } from '../support/projects';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '4d7a2e91-6b3c-4f05-8e1d-9c2b5a7f3e64';
const text = (id: string, words: string) =>
  JSON.stringify({
    type: 'assistant',
    message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] },
    parent_tool_use_id: null,
    session_id: CONVERSATION,
  });

const DECISION = 'Which tent for the trip?\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const TRIP = 'The plan for the trip.\n';
const SLEEP = '## Where do we sleep?\n\n```decision id=D1\noptions:\n  - Tent\n  - Cabin\n```\n';
const draftText = (title: string, slug: string) => [`---\nslug: ${slug}\n---\n`, `# ${title}\n`, 'A week by the lake.\n', SLEEP].join('\n');

type Note = { id: string; summary: string; content: string };
const note = (id: string): Note => ({ id, summary: `Summary ${id}`, content: `Content ${id}` });
const step = (id: string, status: 'pending' | 'in_progress' | 'done', notes: Note[] = []) => ({ id, title: `Step ${id}`, status, notes });

/** A colour as the browser computes it, from the page's tokens: `hsl(var(--primary))`. */
function colourOf(page: Page, colour: string): Promise<string> {
  return page.evaluate((css) => {
    const probe = document.createElement('div');
    probe.style.backgroundColor = css;
    document.body.append(probe);
    const computed = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return computed;
  }, colour);
}

const boxOf = async (locator: Locator) => (await locator.boundingBox())!;

/** The tab's name, its last line of text, where it stands. */
function nameBox(tab: Locator) {
  return tab.evaluate((button) => {
    const range = document.createRange();
    range.selectNode(button.lastChild!);
    const { x, y, width, height } = range.getBoundingClientRect();
    return { x, y, width, height };
  });
}

/** What stands between the head and the tabs fills the space between them, across the screen. */
async function expectBetween(locator: Locator, projectHead: ProjectHeadPage, phoneTabs: PhoneTabsPage) {
  const [box, head, tabs] = await Promise.all([boxOf(locator), boxOf(projectHead.root), boxOf(phoneTabs.root)]);
  expect(box.x).toBe(0);
  expect(box.width).toBeCloseTo(390, 0);
  expect(box.y).toBeCloseTo(head.y + head.height, 0);
  expect(box.y + box.height).toBeCloseTo(tabs.y, 0);
}

test.describe('The tabs at the bottom on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('end the screen: Timeline, Chat, Plan and Documents, each its icon over its name, the Timeline showing in the primary’s tint on its pill; the head has no Discuss, Documents or Draft', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Tabs'), members: [me.handle!] });
    await timeline.open(id);

    await expect(phoneTabs.tabs).toHaveText(['Timeline', 'Chat', 'Plan', 'Documents']);
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    for (const key of ['chat', 'plan', 'documents'] as const) await expect(phoneTabs.tab(key)).toHaveAttribute('aria-selected', 'false');
    expect(await projectHead.controls()).toEqual(['shell.drawer-toggle', 'project.autopilot', 'project.donut', 'project.menu.button']);

    const bar = await boxOf(phoneTabs.root);
    expect(bar.x).toBe(0);
    expect(bar.width).toBe(390);
    expect(bar.y + bar.height).toBe(844);
    await expectBetween(timeline.root, projectHead, phoneTabs);
    for (const tab of await phoneTabs.tabs.all()) {
      const [own, pill, name] = await Promise.all([boxOf(tab), boxOf(tab.locator('.pill')), nameBox(tab)]);
      expect(pill.y + pill.height).toBeLessThanOrEqual(name.y + 0.5);
      expect(pill.x + pill.width / 2).toBeCloseTo(own.x + own.width / 2, 0);
      expect(name.x + name.width / 2).toBeCloseTo(own.x + own.width / 2, 0);
      await expect(tab.locator('.pill svg.icon')).toBeVisible();
    }

    const showing = phoneTabs.tab('timeline');
    await expect(showing).toHaveCSS('color', await colourOf(page, 'hsl(var(--primary-muted-foreground))'));
    await expect(showing.locator('.pill')).toHaveCSS('background-color', await colourOf(page, 'hsl(var(--primary-muted-strong))'));
    await expect(phoneTabs.tab('chat')).toHaveCSS('color', await colourOf(page, 'hsl(var(--muted-foreground))'));
    await expect(phoneTabs.tab('chat').locator('.pill')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  });

  test('Chat and Documents are the side panel’s tabs between the head and the tabs, without its head, the Timeline under them; Chat carries the unread dot and Documents its count on the icon’s corner', async ({
    people,
    projects,
    controller,
    projectHead,
    timeline,
    overlay,
    panel,
    chat,
    chats,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Panel'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    const { session } = await chats.start(id, 'Which tent do we take?');
    await controller.play(chats.store, session, [text('one', 'The dome is lighter.')]);
    await controller.finish(chats.store, session, 'success', 'The dome is lighter.');
    await timeline.open(id);

    await expect(phoneTabs.chatDot).toBeVisible();
    await expect(phoneTabs.tab('chat')).toHaveAccessibleName('Chat, a reply unread');
    await expect(phoneTabs.count).toHaveText('1');
    const [chatPill, dot, documentsPill, count] = await Promise.all([
      boxOf(phoneTabs.tab('chat').locator('.pill')),
      boxOf(phoneTabs.chatDot),
      boxOf(phoneTabs.tab('documents').locator('.pill')),
      boxOf(phoneTabs.count),
    ]);
    // On the icon's top right corner, within the pill.
    expect(dot.x).toBeGreaterThan(chatPill.x + chatPill.width / 2);
    expect(dot.y + dot.height).toBeLessThan(chatPill.y + chatPill.height / 2);
    expect(count.x).toBeGreaterThan(documentsPill.x + documentsPill.width / 2 - 1);
    expect(count.y).toBeLessThan(documentsPill.y);

    const seen = chat.acted('read');
    await phoneTabs.tab('chat').tap();
    await expect(phoneTabs.tab('chat')).toHaveAttribute('aria-selected', 'true');
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'false');
    await expect(chat.texts).toHaveText(['The dome is lighter.']);
    await seen;
    await expect(phoneTabs.chatDot).toHaveCount(0);
    await expect(panel.head).toHaveCount(0);
    await expect(timeline.root).toBeHidden();
    await expectBetween(panel.root, projectHead, phoneTabs);
    const [side, composer] = await Promise.all([boxOf(panel.root), boxOf(chat.composer)]);
    expect(composer.y + composer.height).toBeCloseTo(side.y + side.height, 0);

    await phoneTabs.tab('documents').tap();
    await expect(phoneTabs.tab('documents')).toHaveAttribute('aria-selected', 'true');
    await expect(panel.head).toHaveCount(0);
    await expect(panel.document(trip).title).toHaveText('The trip');
    await expectBetween(panel.root, projectHead, phoneTabs);

    // A row opens in the overlay, over the head and the tabs.
    await panel.document(trip).root.tap();
    await expect(overlay.title).toHaveText('The trip');
    expect(await isOnTop(overlay.root)).toBe(true);
    await expect(overlay.maximize).toBeHidden();
    await expect(
      phoneTabs.tab('chat').evaluate((tab) => {
        const box = tab.getBoundingClientRect();
        return tab.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
      }),
    ).resolves.toBe(false);
  });

  test('Plan is the plan popover’s content as a page, its rows a thumb’s height, a step’s notes listed on a tap; with no steps, none yet', async ({
    people,
    projects,
    projectHead,
    timeline,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({
      name: makeUnique('Plan'),
      members: [me.handle!],
      tasks: [step('a', 'done'), step('b', 'in_progress', [note('tapped')]), step('c', 'in_progress'), step('d', 'pending')],
    });
    const none = await projects.make({ name: makeUnique('Unplanned'), members: [me.handle!] });
    await timeline.open(id);

    await phoneTabs.tab('plan').tap();
    await expect(phoneTabs.tab('plan')).toHaveAttribute('aria-selected', 'true');
    await expect(phoneTabs.plan.heading).toHaveText('The plan · 1 of 4 done');
    await expect(phoneTabs.plan.steps.getByTestId('project.plan.step.title')).toHaveText(['Step a', 'Step b', 'Step c', 'Step d']);
    for (const [index, state] of ['done', 'now', 'now', 'pending'].entries()) {
      await expect(phoneTabs.plan.steps.nth(index)).toHaveAttribute('data-state', state);
    }
    await expect(timeline.root).toBeHidden();
    await expect(projectHead.plan).toHaveCount(0);
    await expectBetween(phoneTabs.plan.root, projectHead, phoneTabs);
    for (const row of await phoneTabs.plan.steps.all()) expect((await boxOf(row)).height).toBeGreaterThanOrEqual(40);

    const noted = phoneTabs.planStep('Step b');
    await noted.notesButton.tap();
    await expect(noted.notes.getByTestId('project.plan.step.notes.note.summary')).toHaveText(['Summary tapped']);
    await noted.notesButton.tap();
    await expect(noted.notes).toHaveCount(0);

    await timeline.open(none);
    await phoneTabs.tab('plan').tap();
    await expect(phoneTabs.plan.heading).toHaveText('The plan');
    await expect(phoneTabs.plan.steps).toHaveCount(0);
    await expect(phoneTabs.plan.none).toHaveText('No steps yet.');
  });

  test('Back from Chat, Plan or Documents shows the Timeline, leaving it the one entry, and Back there leaves the project; a reload keeps the tab; switching projects is an entry, opening on the Timeline', async ({
    page,
    people,
    projects,
    projectList,
    shell,
    timeline,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const before = await projects.makeWithSession({ name: makeUnique('Before'), members: [me.handle!] });
    const id = await projects.makeWithSession({ name: makeUnique('Back'), members: [me.handle!] });
    const otherName = makeUnique('Other');
    const other = await projects.makeWithSession({ name: otherName, members: [me.handle!] });
    await timeline.open(before);
    await timeline.open(id);

    await phoneTabs.tab('chat').tap();
    await phoneTabs.tab('plan').tap();
    await phoneTabs.tab('documents').tap();
    await expect(phoneTabs.tab('documents')).toHaveAttribute('aria-selected', 'true');
    await expect(page).toHaveURL(projectAddress(id));
    await page.reload();
    await waitForUiState(page, 'project.head', 'ready');
    await expect(phoneTabs.tab('documents')).toHaveAttribute('aria-selected', 'true');

    await page.goBack();
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(timeline.root).toBeVisible();
    await expect(page).toHaveURL(projectAddress(id));
    await page.goBack();
    await expect(page).toHaveURL(projectAddress(before));
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await page.goForward();
    await expect(page).toHaveURL(projectAddress(id));
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');

    // The Timeline's tab is Back to it, from any other tab.
    await phoneTabs.tab('plan').tap();
    await phoneTabs.tab('chat').tap();
    await phoneTabs.tab('timeline').tap();
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await page.goBack();
    await expect(page).toHaveURL(projectAddress(before));
    await page.goForward();
    await expect(page).toHaveURL(projectAddress(id));

    await phoneTabs.tab('chat').tap();
    await shell.drawerToggle.tap();
    await projectList.tab(otherName).tap();
    await expect(page).toHaveURL(projectAddress(other));
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await page.goBack();
    await expect(page).toHaveURL(projectAddress(id));
    await expect(phoneTabs.tab('chat')).toHaveAttribute('aria-selected', 'true');
  });

  test('every project opens on its Timeline, whatever panel the browser keeps for it, which the phone leaves as it is', async ({
    page,
    people,
    projects,
    timeline,
    panel,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Kept'), members: [me.handle!] });
    await timeline.open(id);
    const kept = { [id]: { tab: 'documents' } };
    await page.evaluate((panels) => localStorage.setItem('pilot', JSON.stringify({ ...JSON.parse(localStorage.getItem('pilot') ?? '{}'), panels })), kept);
    await timeline.open(id);

    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(panel.root).toHaveCount(0);
    await phoneTabs.tab('chat').tap();
    await expect(panel.root).toBeVisible();
    await phoneTabs.tab('timeline').tap();
    await expect(panel.root).toHaveCount(0);
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('pilot')!).panels)).toEqual(kept);
  });

  test('Discuss on an item, and in a view, shows the Chat tab with the quote in its composer, the view taken off', async ({
    people,
    projects,
    timeline,
    overlay,
    chat,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Discuss'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await timeline.open(id);

    await timeline.item(decision).discuss.tap();
    await expect(phoneTabs.tab('chat')).toHaveAttribute('aria-selected', 'true');
    await expect(chat.quote).toHaveAttribute('data-quote', `item ${decision}`);
    await expect(chat.field).toBeFocused();

    await overlay.open(id, trip);
    await overlay.discuss.tap();
    await expect(overlay.root).toHaveCount(0);
    await expect(phoneTabs.tab('chat')).toHaveAttribute('aria-selected', 'true');
    await expect(chat.quote).toHaveAttribute('data-quote', `item ${trip}`);
  });
});

test.describe('A draft’s tabs on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('are Chat, the definition chat in the timeline’s place with Create project at its end, Draft and Documents; it opens on its Chat, Discuss on an ask shows it, and the quote’s chip shows the Draft tab at the ask', async ({
    page,
    people,
    projects,
    projectHead,
    controller,
    panel,
    definitionChat,
    chats,
    phoneTabs,
  }) => {
    const me = await people.signIn();
    const { id, folder } = await projects.makeDraft({ members: [me.handle!] });
    await projectHead.open(id);
    const opened = await chats.opening(id, folder);
    await definitionChat.field.fill('A week by the lake.');
    await definitionChat.send.tap();
    const session = await opened();
    const title = makeUnique('Lake');
    await projects.saveProjectDocument(id, 'draft', draftText(title, `lake-${makeUniqueToken().toLowerCase()}`));
    await controller.play(chats.store, session, [text('one', 'I drafted the week.')]);
    await controller.finish(chats.store, session, 'success', 'I drafted the week.');

    await expect(phoneTabs.tabs).toHaveText(['Chat', 'Draft', 'Documents']);
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(definitionChat.createButton).toBeVisible();
    await expectBetween(definitionChat.root, projectHead, phoneTabs);

    await phoneTabs.tab('draft').tap();
    await expect(phoneTabs.tab('draft')).toHaveAttribute('aria-selected', 'true');
    await expect(panel.draft.title).toHaveText(title);
    await expect(panel.head).toHaveCount(0);
    await expect(definitionChat.root).toBeHidden();
    await expectBetween(panel.root, projectHead, phoneTabs);
    await phoneTabs.tab('documents').tap();
    await expect(panel.attachments.or(panel.noAttachments)).toBeVisible();
    await page.goBack();
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(definitionChat.root).toBeVisible();

    await phoneTabs.tab('draft').tap();
    await panel.draftBlock('D1').discuss.tap();
    await expect(phoneTabs.tab('timeline')).toHaveAttribute('aria-selected', 'true');
    await expect(definitionChat.quote).toHaveAttribute('data-quote', 'block project.md/D1');
    await expect(definitionChat.field).toBeFocused();

    await definitionChat.field.fill('A tent, surely?');
    const sent = definitionChat.acted('send');
    await definitionChat.send.tap();
    await sent;
    await definitionChat.quotes.tap();
    await expect(phoneTabs.tab('draft')).toHaveAttribute('aria-selected', 'true');
    await expect(panel.draftBlock('D1').root).toHaveClass(/\bflash\b/);
  });
});

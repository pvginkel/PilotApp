/**
 * The side panel (F38.1) and its Documents tab (F37). It has the Chat tab, first and the one it
 * opens on until the person picks another (tests/chat/chat-tab.spec.ts), the Documents tab with its
 * count, and a close cross; the Documents tab lists the project document first, then the attachments newest
 * first, the files of one call under their folder, then the timeline's documents and reviews
 * newest first with Open, *Unsent* or Done and their stamp, each opening in its tab at its
 * address. The head's Documents button toggles it (F2.3). Each project's panel is its own, open or
 * closed and on which tab, kept in the browser (F1.6, F133); until it is set, it stands open. Off a
 * phone, on a wide window and at the narrow width alike, it stands beside the timeline and the tab
 * showing, nothing over it, and Esc never closes it, nor going to an item (F98.1,
 * F98.2); on a phone its tabs are among the tabs at the bottom (tests/projects/phone-tabs.spec.ts). The tab's lists wait on its read, the
 * timeline's and the project document's: nothing under the headings while it is on its way, the
 * project document's row "Project document" until its title is read, and "The documents did not
 * load" in the lists' place where the read fails (F113).
 */

import { randomUUID } from 'node:crypto';
import { test, expect } from '../support/fixtures';
import { expectConsoleError, makeUnique, waitForUiState } from '../support/helpers';
import { slowNetwork } from '../support/network';
import { documentAddress, projectDocumentAddress } from '../support/page-objects/overlay-page';
import { isOnTop } from '../support/page-objects/panel-page';
import { addressOf, attachmentAddress } from '../support/page-objects/timeline-page';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const stamp = (at: string) =>
  new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: ZONE }).format(new Date(at));

const ASKS = [
  'We go in May.\n',
  '## Which tent?\n',
  '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nrecommend: Dome\n```\n',
  '## Where do we pitch?\n',
  '```question id=Q1\ndefault: Lake Garda\n```\n',
].join('\n');
const SETTLED = [
  '## Which tent?\n',
  '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\nanswer: Dome\nby: agent\nat: 2026-10-20T09:00:00Z\n```\n',
  '## Where do we pitch?\n',
  '```question id=Q1\nanswer: Lake Garda\nby: agent\nat: 2026-10-20T09:00:00Z\n```\n',
].join('\n');

interface Placed {
  id: string;
  name: string;
  notice: string;
  packing: string;
  tent: string;
  survey: string;
  route: string;
  map: string;
  kit: string;
  weights: string;
  photos: string;
}

/**
 * A project with a notice, two open documents, the second answered in part, a review and a
 * document Pilot settled and marked Done, in that order; then a file attached to the notice, two
 * in one call to the answered document, and one to the review.
 */
async function placed(people: People, projects: Projects): Promise<Placed> {
  const me = await people.signIn();
  const name = makeUnique('Panel');
  const id = await projects.makeWithSession({ name, members: [me.handle!] });
  const notice = await projects.place(id, { kind: 'notice', title: 'We leave on Friday', text: '# We leave on Friday\n' });
  const packing = await projects.place(id, { kind: 'document', title: 'Packing', text: ASKS });
  const tent = await projects.place(id, { kind: 'document', title: 'The tent', text: ASKS });
  const survey = await projects.place(id, { kind: 'review', title: 'Campsites', text: 'Read the campsites through.\n' });
  const route = await projects.place(id, { kind: 'document', title: 'The route', text: SETTLED });
  await projects.doneByPilot(route);
  await projects.answer(tent, 'D1', 'Tunnel');
  const [map] = await projects.attach(notice, [{ title: 'The map', filename: 'map.txt', content_type: 'text/plain', content: 'North.\n' }]);
  const [kit, weights] = await projects.attach(tent, [
    { title: 'Kit list', filename: 'kit.md', content_type: 'text/markdown', content: '# Kit\n\n- Pegs\n' },
    { title: 'Weights', filename: 'weights.txt', content_type: 'text/plain', content: 'Tent: 2 kg\n' },
  ]);
  const [photos] = await projects.attach(survey, [
    { title: 'Site notes', filename: 'sites.txt', content_type: 'text/plain', content: 'Shade by the lake.\n' },
  ]);
  return { id, name, notice, packing, tent, survey, route, map, kit, weights, photos };
}

test.describe('The side panel on a wide window', () => {
  test('stands open beside the timeline from the start, on its Chat tab, its head lined up with the project’s; its Documents tab, the second, carries the count and lists the project document, the attachments newest first, the files of one call under their folder, and the timeline’s documents and reviews newest first with their state and stamp', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
    panel,
  }) => {
    const p = await placed(people, projects);
    const read = panel.read();
    await timeline.open(p.id);
    await read;
    const { items } = await projects.timeline(p.id);
    const itemOf = (id: string) => items.find((item) => item.id === id)!;
    const attachmentOf = (item: string, id: string) => itemOf(item).attachments.find((attachment) => attachment.id === id)!;

    await expect(panel.root).toBeVisible();
    await expect(panel.head.getByRole('tab')).toHaveText(['Chat', /^Documents/]);
    await expect(panel.documentsTab).toHaveAttribute('aria-selected', 'false');
    await expect(panel.count).toHaveText('8');
    await expect(projectHead.documentsButton).toHaveAttribute('aria-pressed', 'false');
    await panel.documentsTab.click();
    await expect(panel.documentsTab).toHaveAttribute('aria-selected', 'true');
    await expect(projectHead.documentsButton).toHaveAttribute('aria-pressed', 'true');

    await expect(panel.projectDocument.title).toHaveText(p.name);
    await expect(panel.projectDocument.sub).toHaveText('Project document');
    await expect(panel.body.locator('h3')).toHaveText(['Attachments', 'In the timeline']);
    const [first, heading] = await Promise.all([panel.projectDocument.root.boundingBox(), panel.body.locator('h3').first().boundingBox()]);
    expect(first!.y).toBeLessThan(heading!.y);

    await expect(panel.attachments.getByTestId('panel.row.title')).toHaveText(['Site notes', 'Kit list', 'Weights', 'The map']);
    await expect(panel.attachment(p.photos).sub).toHaveText(`Campsites · ${stamp(attachmentOf(p.survey, p.photos).copied_at)}`);
    await expect(panel.attachment(p.map).sub).toHaveText(`We leave on Friday · ${stamp(attachmentOf(p.notice, p.map).copied_at)}`);
    await expect(panel.batches).toHaveCount(1);
    const batch = panel.batch(attachmentOf(p.tent, p.kit).batch);
    await expect(batch.head.title).toHaveText('Invented');
    await expect(batch.head.sub).toHaveText(`The tent · ${stamp(attachmentOf(p.tent, p.kit).copied_at)}`);
    await expect(batch.files.getByTestId('panel.row.title')).toHaveText(['Kit list', 'Weights']);
    await expect(batch.files.getByTestId('panel.row.sub')).toHaveText(['kit.md', 'weights.txt']);

    await expect(panel.documents.getByTestId('panel.row.title')).toHaveText(['The route', 'Campsites', 'The tent', 'Packing']);
    const states = { [p.route]: 'Done', [p.survey]: 'Open', [p.tent]: 'Unsent', [p.packing]: 'Open' };
    for (const [item, state] of Object.entries(states)) {
      await expect(panel.document(item).sub).toHaveText(`${state} · ${stamp(itemOf(item).created_at)}`);
      await expect(panel.document(item).root).toHaveAttribute('data-state', state.toLowerCase());
    }

    const viewport = page.viewportSize()!;
    const [side, feed, head, panelHead] = await Promise.all(
      [panel.root, timeline.root, projectHead.root, panel.head].map(async (locator) => (await locator.boundingBox())!),
    );
    expect(side.width).toBeCloseTo(420, 0);
    expect(side.x + side.width).toBeCloseTo(viewport.width, 0);
    expect(feed.x + feed.width).toBeLessThanOrEqual(side.x + 1);
    expect(head.x + head.width).toBeLessThanOrEqual(side.x + 1);
    expect(panelHead.y).toBeCloseTo(head.y, 0);
    expect(panelHead.height).toBeCloseTo(head.height, 0);
  });

  test('a row opens in its tab at its address, to the panel’s left; its tab’s cross and Close all close the tabs, Esc neither a tab nor the panel', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    docTabs,
    panel,
  }) => {
    const p = await placed(people, projects);
    await timeline.open(p.id);
    await panel.documentsTab.click();

    await panel.projectDocument.root.click();
    await expect(page).toHaveURL(projectDocumentAddress(p.id));
    await expect(overlay.role).toHaveText('Project document');
    const [sheet, side] = await Promise.all([overlay.root.boundingBox(), panel.root.boundingBox()]);
    expect(sheet!.x + sheet!.width).toBeCloseTo(side!.x, 0);
    expect(await isOnTop(panel.root)).toBe(true);
    await page.keyboard.press('Escape');
    await expect(overlay.root).toBeVisible();
    await expect(page).toHaveURL(projectDocumentAddress(p.id));
    await expect(panel.root).toBeVisible();

    await panel.attachment(p.map).root.click();
    await expect(page).toHaveURL(attachmentAddress(p.id, p.notice, p.map));
    await expect(overlay.title).toHaveText('The map');
    await expect(overlay.attachment.text).toHaveText('North.');
    await docTabs.attachment(p.map).close.click();
    await expect(overlay.role).toHaveText('Project document');
    await expect(panel.root).toBeVisible();

    await panel.document(p.tent).root.click();
    await expect(page).toHaveURL(documentAddress(p.id, p.tent));
    await expect(overlay.title).toHaveText('The tent');
    await panel.document(p.survey).root.click();
    await expect(page).toHaveURL(documentAddress(p.id, p.survey));
    await expect(overlay.title).toHaveText('Campsites');
    // The panel's tab chosen beside the tab: Esc closes neither.
    await panel.documentsTab.click();
    await page.keyboard.press('Escape');
    await expect(overlay.title).toHaveText('Campsites');
    await expect(panel.root).toBeVisible();

    await docTabs.closeAll.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${p.id}`);
    await expect(panel.root).toBeVisible();
  });

  test('the head’s Documents button, between the members and the handbook’s, shows its Documents tab and then toggles it, and its cross closes it; each project’s panel comes back as it was left, kept in the browser', async ({
    page,
    people,
    projects,
    projectHead,
    projectList,
    timeline,
    panel,
  }) => {
    const me = await people.signIn();
    const oneName = makeUnique('Kept');
    const one = await projects.makeWithSession({ name: oneName, members: [me.handle!] });
    const otherName = makeUnique('Default');
    const other = await projects.makeWithSession({ name: otherName, members: [me.handle!] });
    await timeline.open(one);

    const [members, documents, handbook] = await Promise.all(
      [projectHead.members, projectHead.documentsButton, projectHead.handbookButton].map(async (locator) => (await locator.boundingBox())!),
    );
    expect(documents.x).toBeGreaterThan(members.x + members.width);
    expect(handbook.x).toBeCloseTo(documents.x + documents.width, 0);
    await expect(projectHead.documentsButton).toHaveAttribute('aria-label', 'The project’s documents');

    await expect(panel.count).toHaveCount(0);
    // Open on the Chat tab, the button shows the Documents tab; on it, the button closes the panel.
    await expect(projectHead.documentsButton).toHaveAttribute('aria-pressed', 'false');
    await projectHead.documentsButton.click();
    await expect(panel.documentsTab).toHaveAttribute('aria-selected', 'true');
    await expect(projectHead.documentsButton).toHaveAttribute('aria-pressed', 'true');
    await expect(panel.noAttachments).toHaveText('None yet. A session attaches reader’s material here: a design, a survey, a log.');
    await expect(panel.noDocuments).toHaveText('None yet.');
    await expect(panel.projectDocument.title).toHaveText(oneName);

    await projectHead.documentsButton.click();
    await expect(panel.root).toHaveCount(0);
    await expect(projectHead.documentsButton).toHaveAttribute('aria-pressed', 'false');
    await projectHead.documentsButton.click();
    await expect(panel.root).toBeVisible();
    await expect(projectHead.documentsButton).toHaveAttribute('aria-pressed', 'true');
    await panel.close.click();
    await expect(panel.root).toHaveCount(0);

    await projectList.tab(otherName).click();
    await expect(page).toHaveURL(`/projects/${other}`);
    await expect(panel.root).toBeVisible();
    await projectList.tab(oneName).click();
    await expect(page).toHaveURL(`/projects/${one}`);
    await expect(projectHead.name).toHaveText(oneName);
    await expect(panel.root).toHaveCount(0);

    await timeline.open(one);
    await expect(projectHead.name).toHaveText(oneName);
    await expect(panel.root).toHaveCount(0);
    const kept = await page.evaluate(() => (JSON.parse(localStorage.getItem('pilot')!) as { panels: Record<string, unknown> }).panels);
    expect(kept[one]).toEqual({ open: false, tab: 'documents' });
    expect(kept[other]).toBeUndefined();
  });

  test('stands only once the project’s head is read: not at an address naming no project', async ({ page, people, panel }) => {
    await people.signIn();
    await page.goto(`/projects/${randomUUID()}`);
    await waitForUiState(page, 'project.head', 'ready');
    await expect(panel.root).toHaveCount(0);
  });
});

test.describe('The Documents tab’s read', () => {
  test('draws nothing under its headings while it is on its way, the project document’s row named “Project document” until its title is read; then “None yet.” under each list read empty', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
    panel,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Pending');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    // Closed, and the page opened afresh: the timeline is read before the tab opens, and the
    // project document's read, which the tab alone makes, goes out as it opens.
    await timeline.open(id);
    await panel.close.click();
    await timeline.open(id);
    await expect(panel.root).toHaveCount(0);

    const restore = await slowNetwork(page, 1_000);
    const read = panel.read();
    await projectHead.documentsButton.click();
    await expect(panel.headings).toHaveText(['Attachments', 'In the timeline']);
    await expect(panel.projectDocument.title).toHaveText('Project document');
    await expect(panel.projectDocument.sub).toHaveText('Project document');
    await expect(panel.noAttachments).toHaveCount(0);
    await expect(panel.noDocuments).toHaveCount(0);
    await expect(panel.failed).toHaveCount(0);

    await read;
    await restore();
    await expect(panel.projectDocument.title).toHaveText(name);
    await expect(panel.noAttachments).toHaveText('None yet. A session attaches reader’s material here: a design, a survey, a log.');
    await expect(panel.noDocuments).toHaveText('None yet.');
    await expect(panel.failed).toHaveCount(0);
  });

  test('says “The documents did not load” in the lists’ place where it fails, the row named “Project document”, and draws the lists once a later read lands', async ({
    page,
    auth,
    people,
    projects,
    projectHead,
    timeline,
    panel,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Failed');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    await projects.place(id, { kind: 'document', title: 'Packing', text: 'We pack light.\n' });
    await timeline.open(id);
    await panel.close.click();
    await timeline.open(id);
    await expect(panel.root).toHaveCount(0);

    // The browser's session now lacks the editor role, and the API refuses the tab's read.
    await expectConsoleError(page, /403/);
    await auth.createSession({ name: 'Test Person', roles: [] });
    await projectHead.documentsButton.click();
    await expect(panel.failed).toHaveText('The documents did not load.');
    await expect(panel.headings).toHaveCount(0);
    await expect(panel.documents).toHaveCount(0);
    await expect(panel.noAttachments).toHaveCount(0);
    await expect(panel.projectDocument.title).toHaveText('Project document');
    await expect(panel.count).toHaveCount(0);

    await people.firstSignIn();
    await timeline.refocus();
    await expect(panel.failed).toHaveCount(0);
    await expect(panel.projectDocument.title).toHaveText(name);
    await expect(panel.headings).toHaveText(['Attachments', 'In the timeline']);
    await expect(panel.documents.getByTestId('panel.row.title')).toHaveText(['Packing']);
    await expect(panel.count).toHaveText('1');
  });
});

test.describe('The side panel at the narrow width', () => {
  test.use({ viewport: { width: 1100, height: 800 } });

  test('stands open from the start beside the timeline, at 901 px and 1199 px too, its head lined up with the project’s; a row opens in its tab to its left, nothing over the panel, Esc closing neither, nor going to an item', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
    overlay,
    docTabs,
    panel,
  }) => {
    const p = await placed(people, projects);
    await timeline.open(p.id);
    await expect(panel.root).toBeVisible();
    const beside = async (width: number) => {
      const [side, feed, head, panelHead] = await Promise.all(
        [panel.root, timeline.root, projectHead.root, panel.head].map(async (locator) => (await locator.boundingBox())!),
      );
      expect(side.width).toBeCloseTo(420, 0);
      expect(side.x + side.width).toBeCloseTo(width, 0);
      expect(feed.x + feed.width).toBeLessThanOrEqual(side.x + 1);
      expect(head.x + head.width).toBeLessThanOrEqual(side.x + 1);
      expect(panelHead.y).toBeCloseTo(head.y, 0);
      expect(panelHead.height).toBeCloseTo(head.height, 0);
    };
    await beside(1100);
    await page.keyboard.press('Escape');
    await expect(panel.root).toBeVisible();

    await panel.documentsTab.click();
    await panel.document(p.tent).root.click();
    await expect(overlay.title).toHaveText('The tent');
    const [sheet, side] = await Promise.all([overlay.root.boundingBox(), panel.root.boundingBox()]);
    expect(sheet!.x + sheet!.width).toBeCloseTo(side!.x, 0);
    expect(await isOnTop(overlay.root)).toBe(true);
    expect(await isOnTop(panel.root)).toBe(true);
    await expect(panel.root).not.toHaveAttribute('inert');
    await panel.document(p.packing).root.click();
    await expect(overlay.title).toHaveText('Packing');
    await page.keyboard.press('Escape');
    await expect(overlay.title).toHaveText('Packing');
    await expect(panel.root).toBeVisible();
    await docTabs.closeAll.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(panel.root).toBeVisible();

    await timeline.openAt(p.id, p.notice);
    await expect(page).toHaveURL(addressOf(p.id, p.notice));
    await expect(panel.root).toBeVisible();
    for (const width of [901, 1199]) {
      await page.setViewportSize({ width, height: 800 });
      await expect.poll(async () => (await panel.root.boundingBox())!.x).toBeCloseTo(width - 420, 0);
      await beside(width);
    }
  });
});

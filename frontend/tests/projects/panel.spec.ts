/**
 * The side panel (F38.1) and its Documents tab (F37). It has the Documents tab alone, with its
 * count, and a close cross; the tab lists the project document first, then the attachments newest
 * first, the files of one call under their folder, then the timeline's documents and reviews
 * newest first with Open, *Unsent* or Done and their stamp, each opening in the overlay at its
 * address. The head's Documents button toggles it (F2.3). Each project's panel is its own, open or
 * closed and on which tab, kept in the browser (F1.6, F133); until it is set, it stands open on a
 * window 1200 px wide or more. On a wide window it stands beside the timeline and the overlay
 * beside it, and Esc never closes it (F98.1); below that it lies over the timeline, it and the
 * overlay the one opened last on top and the first Esc closes, and going to an item closes it
 * (F98.2); on a phone it is the whole screen (F98.3).
 */

import { randomUUID } from 'node:crypto';
import { test, expect } from '../support/fixtures';
import { makeUnique, waitForUiState } from '../support/helpers';
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
  test('stands open beside the timeline from the start, its head lined up with the project’s; its Documents tab, the only one, lists the project document, the attachments newest first, the files of one call under their folder, and the timeline’s documents and reviews newest first with their state and stamp, and carries the count', async ({
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
    await expect(panel.head.getByRole('tab')).toHaveCount(1);
    await expect(panel.documentsTab).toContainText('Documents');
    await expect(panel.documentsTab).toHaveAttribute('aria-selected', 'true');
    await expect(panel.count).toHaveText('8');
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

  test('a row opens in the overlay at its address, to the panel’s left; Esc, the cross and the backdrop close the overlay, never the panel', async ({
    page,
    people,
    projects,
    timeline,
    overlay,
    panel,
  }) => {
    const p = await placed(people, projects);
    await timeline.open(p.id);

    await panel.projectDocument.root.click();
    await expect(page).toHaveURL(projectDocumentAddress(p.id));
    await expect(overlay.role).toHaveText('Project document');
    const [sheet, side] = await Promise.all([overlay.root.boundingBox(), panel.root.boundingBox()]);
    expect(sheet!.x + sheet!.width).toBeCloseTo(side!.x, 0);
    expect(await isOnTop(panel.root)).toBe(true);
    await page.keyboard.press('Escape');
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(`/projects/${p.id}`);
    await expect(panel.root).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(panel.root).toBeVisible();

    await panel.attachment(p.map).root.click();
    await expect(page).toHaveURL(attachmentAddress(p.id, p.notice, p.map));
    await expect(overlay.title).toHaveText('The map');
    await expect(overlay.attachment.text).toHaveText('North.');
    await overlay.close.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(panel.root).toBeVisible();

    await panel.document(p.tent).root.click();
    await expect(page).toHaveURL(documentAddress(p.id, p.tent));
    await expect(overlay.title).toHaveText('The tent');
    await panel.document(p.survey).root.click();
    await expect(page).toHaveURL(documentAddress(p.id, p.survey));
    await expect(overlay.title).toHaveText('Campsites');
    // The panel's tab chosen beside the overlay: Esc still closes the overlay.
    await panel.documentsTab.click();
    await page.keyboard.press('Escape');
    await expect(overlay.root).toHaveCount(0);
    await expect(panel.root).toBeVisible();

    await panel.document(p.survey).root.click();
    await expect(overlay.title).toHaveText('Campsites');
    await overlay.backdrop.click({ position: { x: 5, y: 5 } });
    await expect(overlay.root).toHaveCount(0);
    await expect(panel.root).toBeVisible();
  });

  test('the head’s Documents button, between the members and the handbook’s, toggles it, and its cross closes it; each project’s panel comes back as it was left, kept in the browser', async ({
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

test.describe('The side panel below 1200 px', () => {
  test.use({ viewport: { width: 1100, height: 800 } });

  test('starts closed and lies over the timeline; it and the overlay lie over each other, the one opened last on top, which Esc closes first; with no overlay open Esc leaves it alone', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
    overlay,
    panel,
  }) => {
    const p = await placed(people, projects);
    await timeline.open(p.id);
    await expect(panel.root).toHaveCount(0);
    await expect(projectHead.documentsButton).toHaveAttribute('aria-pressed', 'false');

    await projectHead.documentsButton.click();
    await expect(panel.root).toBeVisible();
    const [side, feed] = await Promise.all([panel.root.boundingBox(), timeline.root.boundingBox()]);
    expect(side!.x + side!.width).toBeCloseTo(1100, 0);
    expect(side!.width).toBeCloseTo(420, 0);
    expect(feed!.x + feed!.width).toBeGreaterThan(side!.x + 100);
    await page.keyboard.press('Escape');
    await expect(panel.root).toBeVisible();

    // A row opened: the overlay on top, and Esc shows the panel again.
    await panel.document(p.tent).root.click();
    await expect(overlay.title).toHaveText('The tent');
    expect(await isOnTop(overlay.root)).toBe(true);
    expect(await isOnTop(panel.root)).toBe(false);
    await page.keyboard.press('Escape');
    await expect(overlay.root).toHaveCount(0);
    await expect(panel.root).toBeVisible();
    expect(await isOnTop(panel.root)).toBe(true);

    // The overlay open, then the panel: the panel on top, and Esc shows the overlay again.
    await panel.document(p.tent).root.click();
    await expect(overlay.title).toHaveText('The tent');
    await projectHead.documentsButton.focus();
    await page.keyboard.press('Enter');
    await expect(panel.root).toHaveCount(0);
    await page.keyboard.press('Enter');
    await expect(panel.root).toBeVisible();
    expect(await isOnTop(panel.root)).toBe(true);
    await page.keyboard.press('Escape');
    await expect(panel.root).toHaveCount(0);
    await expect(overlay.title).toHaveText('The tent');
    expect(await isOnTop(overlay.root)).toBe(true);

    // The panel over the overlay, and a row opened from it: the overlay on top again.
    await page.keyboard.press('Enter');
    expect(await isOnTop(panel.root)).toBe(true);
    await panel.document(p.packing).root.click();
    await expect(overlay.title).toHaveText('Packing');
    expect(await isOnTop(overlay.root)).toBe(true);
    await page.keyboard.press('Escape');
    await expect(overlay.root).toHaveCount(0);
    await expect(panel.root).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(panel.root).toBeVisible();
  });

  test('going to an item closes it, at the item’s address opened or gone back to', async ({ page, people, projects, projectHead, timeline, overlay, panel }) => {
    const p = await placed(people, projects);
    await timeline.open(p.id);
    await projectHead.documentsButton.click();
    await expect(panel.root).toBeVisible();

    await timeline.openAt(p.id, p.notice);
    await expect(panel.root).toHaveCount(0);

    await projectHead.documentsButton.click();
    await expect(panel.root).toBeVisible();
    await panel.document(p.tent).root.click();
    await expect(overlay.title).toHaveText('The tent');
    await page.keyboard.press('Escape');
    await expect(overlay.root).toHaveCount(0);
    await expect(panel.root).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(documentAddress(p.id, p.tent));
    await expect(panel.root).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(addressOf(p.id, p.notice));
    await expect(panel.root).toHaveCount(0);
  });

  test('stands open from the start on a window 1200 px wide, and closed one pixel narrower, following the window until it is set', async ({
    page,
    people,
    projects,
    timeline,
    panel,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Threshold'), members: [me.handle!] });
    await page.setViewportSize({ width: 1199, height: 800 });
    await timeline.open(id);
    await expect(panel.root).toHaveCount(0);
    await page.setViewportSize({ width: 1200, height: 800 });
    await expect(panel.root).toBeVisible();
    const [side, feed] = await Promise.all([panel.root.boundingBox(), timeline.root.boundingBox()]);
    expect(feed!.x + feed!.width).toBeLessThanOrEqual(side!.x + 1);
    await page.setViewportSize({ width: 1199, height: 800 });
    await expect(panel.root).toHaveCount(0);
  });
});

test.describe('The side panel on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('is the whole screen, the overlay over it when a row opens, Esc showing it again, and its cross closes it', async ({
    page,
    people,
    projects,
    projectHead,
    timeline,
    overlay,
    panel,
  }) => {
    const p = await placed(people, projects);
    await timeline.open(p.id);
    await expect(panel.root).toHaveCount(0);

    await projectHead.documentsButton.click();
    await expect(panel.root).toBeVisible();
    const side = (await panel.root.boundingBox())!;
    expect(side.x).toBe(0);
    expect(side.width).toBeCloseTo(390, 0);
    expect(side.y + side.height).toBeCloseTo(844, 0);

    await panel.document(p.survey).root.click();
    await expect(overlay.title).toHaveText('Campsites');
    expect(await isOnTop(overlay.root)).toBe(true);
    await expect(overlay.maximize).toBeHidden();
    await page.keyboard.press('Escape');
    await expect(overlay.root).toHaveCount(0);
    expect(await isOnTop(panel.root)).toBe(true);

    await panel.close.click();
    await expect(panel.root).toHaveCount(0);
  });
});

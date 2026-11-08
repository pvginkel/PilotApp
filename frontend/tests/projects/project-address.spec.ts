/**
 * A project's address (H3): a created project is at `/projects/<slug>` and a draft at
 * `/projects/draft-<number>`, the links in the app taking them; its id opens it too, giving way to
 * its own address in the address bar, the rest of the path kept, and so does a created project's
 * `draft-<number>` (tests/projects/create-project.spec.ts). What the browser keeps of a project is
 * kept by its id, so that it is the same at each of its addresses; a page's beat names the project
 * by its id (tests/shell/beat.spec.ts).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { documentAddress } from '../support/page-objects/overlay-page';
import { projectAddress, slugOf } from '../support/projects';

const WORDS = Array.from({ length: 160 }, (_, index) => `word${index}`).join(' ');
/** A document of two asks, long enough to be a card on the timeline. */
const TRIP = `---\ntitle: The trip\n---\n\n${WORDS}\n\n## Which tent?\n\n\`\`\`question id=Q1\n\`\`\`\n\n## Which stove?\n\n\`\`\`question id=Q2\n\`\`\`\n`;

test.describe("A project's address", () => {
  test('a created project is at its slug, which its row links; at its id it gives way to the slug, the rest of the path kept', async ({
    page,
    people,
    projects,
    projectHead,
    projectList,
    overlay,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Lake');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    expect(projectAddress(id)).toBe(`/projects/${slugOf(id)}`);

    await page.goto(projectAddress(id));
    await expect(projectHead.name).toHaveText(name);
    await expect(projectList.tab(name)).toHaveAttribute('href', projectAddress(id));
    await expect(page).toHaveURL(projectAddress(id));

    await page.goto(`/projects/${id}/documents/${trip}`);
    await expect(page).toHaveURL(documentAddress(id, trip));
    await expect(overlay.title).toHaveText('The trip');
    await expect(projectHead.name).toHaveText(name);
  });

  test('at its id, a project no list holds gives way to its slug on the same screen, drawn once', async ({ page, people, projects, projectHead }) => {
    const me = await people.signIn();
    const name = makeUnique('Shelved');
    const id = await projects.make({ name, archived: true, members: [me.handle!] });
    // Whether the head, once drawn, was taken off the page, as a screen drawn afresh takes it.
    await page.addInitScript(() => {
      const head = '[data-testid="project.head"]';
      new MutationObserver((records) => {
        const removed = records.flatMap((record) => Array.from(record.removedNodes));
        if (removed.some((node) => node instanceof Element && (node.matches(head) || node.querySelector(head) !== null))) {
          document.documentElement.dataset.headRemoved = 'yes';
        }
      }).observe(document, { childList: true, subtree: true });
    });

    await page.goto(`/projects/${id}`);
    await expect(page).toHaveURL(projectAddress(id));
    await expect(projectHead.name).toHaveText(name);
    await expect(page.locator('html')).not.toHaveAttribute('data-head-removed');
  });

  test('a draft is at its draft’s name, which its row links; at its id it gives way to the name', async ({ page, people, projects, projectHead, projectList }) => {
    const me = await people.signIn();
    const { id, folder } = await projects.makeDraft({ members: [me.handle!] });
    expect(folder).toMatch(/^draft-\d+$/);

    await page.goto(`/projects/${folder}`);
    await expect(projectHead.draft).toHaveText('Draft');
    await expect(projectList.tab('New project', projectList.mine)).toHaveAttribute('href', `/projects/${folder}`);
    await expect(page).toHaveURL(`/projects/${folder}`);

    await page.goto(`/projects/${id}`);
    await expect(page).toHaveURL(`/projects/${folder}`);
    await expect(projectHead.draft).toHaveText('Draft');
  });

  test('what the browser keeps of a project is the same at each of its addresses, kept once, by its id: its tab line and its words not sent', async ({
    page,
    people,
    projects,
    timeline,
    panel,
    docTabs,
    chat,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Kept'), members: [me.handle!] });
    const trip = await projects.place(id, { kind: 'document', title: 'The trip', text: TRIP });
    await timeline.open(id);
    await panel.documentsTab.click();
    await panel.document(trip).root.click();
    await expect(page).toHaveURL(documentAddress(id, trip));
    await chat.tab.click();
    await chat.field.fill('Which stove?');

    await page.goto(`/projects/${id}`);
    await expect(page).toHaveURL(projectAddress(id));
    await expect(docTabs.first).toHaveAttribute('aria-selected', 'true');
    expect(await docTabs.keys()).toEqual([`document ${trip}`]);
    await expect(chat.field).toHaveValue('Which stove?');
    const kept = await page.evaluate(() => ({
      lines: Object.keys((JSON.parse(localStorage.getItem('pilot')!) as { lines: Record<string, unknown> }).lines),
      unsent: Object.keys(JSON.parse(localStorage.getItem('pilot.unsent')!) as Record<string, unknown>),
    }));
    expect(kept).toEqual({ lines: [id], unsent: [`chat/${id}`] });
  });
});

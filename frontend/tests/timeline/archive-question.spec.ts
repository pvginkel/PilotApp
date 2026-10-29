/**
 * The archive question (F5.6, D061): after a finish, one question of the server's under the end
 * divider, "Archive the project?", with Archive and Keep. Archive archives the project as the
 * menu's Archive does, its tab leaving the list for Archived (F128.1); Keep closes it, the project
 * staying finished. Either way its done line stays under the divider, with no Undo. Opened at its
 * address, the overlay draws the open question's Archive and Keep in its block's place.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

test.describe('The archive question', () => {
  test('stands under the end divider after a finish, with Archive and Keep, the badge counting it', async ({
    people,
    projects,
    projectList,
    timeline,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Asked');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    await projects.transition(id, 'finished');
    const question = (await projects.timeline(id)).items.at(-1)!;
    await timeline.open(id);

    const item = timeline.item(question.id);
    await expect(item.root).toHaveAttribute('data-kind', 'archive_question');
    await expect(item.root).toHaveAttribute('data-state', 'open');
    await expect(item.title).toHaveText('Archive the project?');
    await expect(item.archiveQuestion.archive).toHaveText('Archive');
    await expect(item.archiveQuestion.keep).toHaveText('Keep');
    const rows = await timeline.rowsRead();
    expect(rows.slice(-2).map(([testId]) => testId)).toEqual(['timeline.divider.finished', 'timeline.item']);
    await expect(projectList.badge(name)).toHaveText('1');
  });

  test('Keep closes it, its done line staying under the divider with no Undo', async ({ people, projects, projectHead, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Kept'), members: [me.handle!] });
    await projects.transition(id, 'finished');
    const question = (await projects.timeline(id)).items.at(-1)!;
    await timeline.open(id);
    const item = timeline.item(question.id);

    await item.archiveQuestion.keep.click();

    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.lineTitle).toHaveText('Archive the project?');
    await expect(item.said).toHaveText('Keep');
    await expect(item.undo).toHaveCount(0);
    await expect(projectHead.finished).toBeVisible();
    await expect(projectHead.archived).toHaveCount(0);
    const rows = await timeline.rowsRead();
    expect(rows.slice(-2).map(([testId]) => testId)).toEqual(['timeline.divider.finished', 'timeline.item']);
  });

  test('opened at its address, it stands as Archive and Keep in its block’s place, with no words to type', async ({
    people,
    projects,
    overlay,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Addressed'), members: [me.handle!] });
    await projects.transition(id, 'finished');
    const question = (await projects.timeline(id)).items.at(-1)!;
    await overlay.open(id, question.id);

    await expect(overlay.title).toHaveText('Archive the project?');
    await expect(overlay.archiveQuestion.archive).toHaveText('Archive');
    await expect(overlay.archiveQuestion.keep).toHaveText('Keep');
    await expect(overlay.blocks).toHaveCount(0);

    await overlay.archiveQuestion.keep.click();

    await expect(overlay.done).toBeVisible();
    await expect(overlay.archiveQuestion.keep).toHaveCount(0);
    await expect(overlay.blocks).toHaveCount(1);
  });

  test('Archive takes the project off the list for Archived, as the menu’s Archive does', async ({
    people,
    projects,
    projectHead,
    projectList,
    timeline,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Archived');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    await projects.transition(id, 'finished');
    const question = (await projects.timeline(id)).items.at(-1)!;
    await timeline.open(id);
    const finished = projectList.group('finished').root;
    await expect(projectList.tab(name, finished)).toBeVisible();
    const item = timeline.item(question.id);

    await item.archiveQuestion.archive.click();

    await expect(projectHead.archived).toBeVisible();
    await expect(projectList.tab(name, finished)).toHaveCount(0);
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.said).toHaveText('Archive');
    await expect(item.undo).toHaveCount(0);
  });
});

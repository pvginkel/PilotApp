/**
 * The archive question (F5.6, D061): after a finish, one question of the server's under the end
 * divider, "Archive the project?", with Archive and Keep, each chosen first and then sent, as in
 * every one-ask item (F32.3). Archive archives the project as the
 * menu's Archive does, its tab leaving the list for Archived (F128.1); Keep closes it, the project
 * staying finished. Either way its done line stays under the divider, with no Undo. Opened at its
 * address, the overlay draws the open question's Archive and Keep in its block's place. Pilot's
 * Finish and archive places none (F5.4): the divider ends the timeline, and the question of a finish
 * before a Reopen keeps its place among the items.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

test.describe('The archive question', () => {
  test('stands under the end divider after a finish, with Archive and Keep, plain buttons, and Send waiting at their row’s end, the badge counting it', async ({
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
    await expect(item.archiveQuestion.archive).toHaveClass('btn');
    await expect(item.archiveQuestion.keep).toHaveClass('btn');
    await expect(item.archiveQuestion.send).toHaveText('Send');
    await expect(item.archiveQuestion.send.locator('svg')).toHaveClass(/\blucide-send\b/);
    await expect(item.archiveQuestion.send).toBeDisabled();
    const send = (await item.archiveQuestion.send.boundingBox())!;
    const keep = (await item.archiveQuestion.keep.boundingBox())!;
    const row = (await item.root.locator('.item-actions').boundingBox())!;
    expect(send.y).toBeCloseTo(keep.y, 0);
    expect(send.x + send.width).toBeCloseTo(row.x + row.width, 0);
    const rows = await timeline.rowsRead();
    expect(rows.slice(-2).map(([testId]) => testId)).toEqual(['timeline.divider.finished', 'timeline.item']);
    await expect(projectList.badge(name)).toHaveText('1');
  });

  test('Keep, chosen and then sent, closes it, its done line staying under the divider with no Undo', async ({ people, projects, projectHead, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Kept'), members: [me.handle!] });
    await projects.transition(id, 'finished');
    const question = (await projects.timeline(id)).items.at(-1)!;
    await timeline.open(id);
    const item = timeline.item(question.id);

    // A press only chooses, and another moves the choice.
    await item.archiveQuestion.archive.click();
    await expect(item.archiveQuestion.archive).toHaveClass('btn btn-soft');
    await item.archiveQuestion.keep.click();
    await expect(item.archiveQuestion.keep).toHaveClass('btn btn-soft');
    await expect(item.archiveQuestion.archive).toHaveClass('btn');
    await expect(item.root).toHaveAttribute('data-state', 'open');
    expect((await projects.block(id, question.id)).answer).toBeNull();
    // The choice stands again after a reload.
    await timeline.open(id);
    await expect(item.archiveQuestion.keep).toHaveAttribute('data-chosen', 'true');
    await item.archiveQuestion.send.click();

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

    await expect(overlay.archiveQuestion.send).toBeDisabled();
    await overlay.archiveQuestion.keep.click();
    await expect(overlay.doneChip).toHaveCount(0);
    await overlay.archiveQuestion.send.click();

    await expect(overlay.done).toBeVisible();
    await expect(overlay.archiveQuestion.keep).toHaveCount(0);
    await expect(overlay.blocks).toHaveCount(1);
  });

  test('Archive, chosen and then sent, takes the project off the list for Archived, as the menu’s Archive does', async ({
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
    await expect(item.archiveQuestion.archive).toHaveAttribute('data-chosen', 'true');
    await expect(projectHead.archived).toHaveCount(0);
    await expect(projectList.tab(name, finished)).toBeVisible();
    await item.archiveQuestion.send.click();

    await expect(projectHead.archived).toBeVisible();
    await expect(projectList.tab(name, finished)).toHaveCount(0);
    await expect(item.root).toHaveAttribute('data-state', 'done');
    await expect(item.said).toHaveText('Archive');
    await expect(item.undo).toHaveCount(0);
  });

  test('after a Finish and archive none stands under the divider, an earlier finish’s question in its place', async ({
    people,
    projects,
    chats,
    projectHead,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Twice'), members: [me.handle!] });
    await projects.transition(id, 'finished');
    const question = (await projects.timeline(id)).items.at(-1)!;
    await projects.transition(id, 'reopened');
    await chats.start(id, 'Finish and archive it.');
    await chats.finish(id, { archive: true });
    await timeline.open(id);

    await expect(projectHead.archived).toBeVisible();
    await expect(timeline.finishedEnd).toBeVisible();
    const item = timeline.item(question.id);
    await expect(item.root).toHaveAttribute('data-kind', 'archive_question');
    await expect(item.said).toHaveText('Keep');
    const rows = await timeline.rowsRead();
    expect(rows.at(-1)![0]).toBe('timeline.divider.finished');
  });
});

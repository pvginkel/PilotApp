/**
 * The Finished end (F5.3): once a project is finished every item the timeline draws is a done
 * line, the opening as it was, and the timeline ends in "Finished · <stamp>"; its tab stands under
 * Finished (F1.5), and no urgent banner is pinned (F10.2).
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

// The browser's time zone, which every time on the timeline is shown in.
const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });

const stamp = (at: string) =>
  new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: ZONE }).format(new Date(at));
const fullStamp = (at: string) =>
  new Intl.DateTimeFormat('en-GB', { dateStyle: 'full', timeStyle: 'long', timeZone: ZONE }).format(new Date(at));

const QUESTION = '```question id=Q1\n```\n';
const DECISION = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';
const URGENT_QUESTION = `---\nurgent: true\n---\n\n${QUESTION}`;

test.describe('A finished project’s timeline', () => {
  test('draws every item as a done line, the opening as it was, and ends in “Finished · <stamp>”', async ({
    people,
    projects,
    timeline,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({
      name: makeUnique('Done'),
      members: [me.handle!],
      opening: 'Let us go camping.',
    });
    const answered = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await projects.answer(answered, 'Q1', 'North');
    const placed = [
      answered,
      await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION }),
      await projects.place(id, { kind: 'notice', title: 'News', text: 'One.\n' }),
      await projects.place(id, { kind: 'question', title: 'Storm coming?', text: URGENT_QUESTION }),
    ];
    await projects.transition(id, 'finished');
    await timeline.open(id);

    for (const item of placed) {
      await expect(timeline.item(item).root).toHaveAttribute('data-state', 'done');
      await expect(timeline.item(item).line).toBeVisible();
    }
    await expect(timeline.openingWords).toHaveText('Let us go camping.');
    await expect(timeline.banners).toHaveCount(0);

    const { finished_at } = await projects.timeline(id);
    const rows = await timeline.rowsRead();
    expect(rows.at(-1)).toEqual(['timeline.divider.finished', `Finished · ${stamp(finished_at!)}`]);
    await expect(timeline.finishedTime).toHaveAttribute('title', fullStamp(finished_at!));
  });

  test('reaches an open timeline when the project is finished elsewhere, its tab moving under Finished', async ({
    people,
    projects,
    projectHead,
    projectList,
    timeline,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Elsewhere');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    const ask = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await timeline.open(id);
    await deploymentSse.ensureConnected();
    await expect(projectList.tab(name, projectList.mine)).toBeVisible();
    await expect(timeline.finishedEnd).toHaveCount(0);

    await projects.transition(id, 'finished');
    await expect(timeline.item(ask).line).toBeVisible();
    await expect(timeline.finishedEnd).toBeVisible();
    await expect(projectHead.finished).toBeVisible();
    await expect(projectList.tab(name, projectList.group('finished').root)).toBeVisible();
    await expect(projectList.tab(name, projectList.mine)).toHaveCount(0);
  });

  test('pins no banner, not even over an urgent item placed after Finish', async ({ people, projects, timeline }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Late'), members: [me.handle!] });
    await projects.transition(id, 'finished');
    const storm = await projects.place(id, { kind: 'question', title: 'Storm coming?', text: URGENT_QUESTION });
    await timeline.open(id);

    await expect(timeline.item(storm).root).toHaveAttribute('data-state', 'open');
    await expect(timeline.item(storm).root).toHaveClass(/\burgent\b/);
    await expect(timeline.banners).toHaveCount(0);
    await expect(timeline.finishedEnd).toBeVisible();
  });
});

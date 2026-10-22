/**
 * A tab's badge (F1.4): the items waiting on the signed-in person, as the API counts them — a
 * notice only when urgent, none for the other person — in the mockup's orange when one is urgent.
 */

import { test, expect } from '../support/fixtures';
import { coloursOf } from '../support/contrast';
import { makeUnique } from '../support/helpers';

const QUESTION = '```question id=Q1\n```\n';
const DECISION = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';

test.describe('A tab’s badge', () => {
  test('counts the items waiting on you: not a notice, nor an item for the other person', async ({
    people,
    projects,
    projectList,
  }) => {
    const ben = makeUnique('ben', 8);
    await people.other(ben, 'Ben Example');
    const me = await people.signIn();
    const name = makeUnique('Badge');
    const id = await projects.makeWithSession({ name, members: [me.handle!, ben] });
    await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await projects.place(id, { kind: 'notice', title: 'News', text: 'One.\n' });
    await projects.place(id, { kind: 'question', title: 'Hers', text: `---\nfor: ${ben}\n---\n\n${QUESTION}` });
    await projectList.open(id);

    const badge = projectList.badge(name);
    await expect(badge).toHaveText('2');
    await expect(badge).toHaveAttribute('title', '2 waiting on you');
    await expect(badge).toHaveAttribute('data-urgent', 'false');
    expect((await projects.list()).find((tab) => tab.id === id)!.badge).toEqual({ count: 2, urgent: false });
  });

  test('stands on no tab with nothing waiting', async ({ people, projects, projectList }) => {
    const me = await people.signIn();
    const name = makeUnique('Calm');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    await projects.place(id, { kind: 'notice', title: 'News', text: 'One.\n' });
    await projectList.open(id);

    await expect(projectList.tab(name)).toBeVisible();
    await expect(projectList.badge(name)).toHaveCount(0);
  });

  test('is orange when one of the items is urgent, an urgent notice counted, readable in light and dark', async ({
    page,
    people,
    projects,
    projectList,
  }) => {
    const me = await people.signIn();
    const calmName = makeUnique('Calm');
    const urgentName = makeUnique('Urgent');
    const calm = await projects.makeWithSession({ name: calmName, members: [me.handle!] });
    await projects.place(calm, { kind: 'question', title: 'Which lake?', text: QUESTION });
    const urgent = await projects.makeWithSession({ name: urgentName, members: [me.handle!] });
    await projects.place(urgent, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await projects.place(urgent, { kind: 'notice', title: 'Storm', text: '---\nurgent: true\n---\n\nA storm comes.\n' });

    for (const scheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await projectList.open(calm);
      await expect(page.locator('html')).toHaveAttribute('data-theme', scheme);
      const urgentBadge = projectList.badge(urgentName);
      await expect(urgentBadge).toHaveText('2');
      await expect(urgentBadge).toHaveAttribute('data-urgent', 'true');
      await expect(projectList.badge(calmName)).toHaveAttribute('data-urgent', 'false');

      const orange = await coloursOf(urgentBadge);
      const blue = await coloursOf(projectList.badge(calmName));
      const [red, green, b] = orange.background;
      expect(red > green && green > b, `orange in ${scheme}: ${orange.background}`).toBe(true);
      expect(blue.background[2], `blue in ${scheme}: ${blue.background}`).toBeGreaterThan(blue.background[0]);
      expect(orange.ratio, `the urgent badge's contrast in ${scheme}`).toBeGreaterThanOrEqual(4.5);
      expect(blue.ratio, `the badge's contrast in ${scheme}`).toBeGreaterThanOrEqual(4.5);
    }
  });
});

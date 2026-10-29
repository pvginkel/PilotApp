/**
 * An action of a registered document Pilot claimed (F21.6): open until its Done, Pilot's, its block
 * reading "Pilot does it" with the claim's note and a link to the work item the claim names, inline
 * and in the overlay, over a person's controls; the document's *Send answers* waits on it. A
 * person who does it meanwhile marks it Done as any action's Done, the claim gone.
 */

import { test, expect } from '../support/fixtures';
import type { Controller } from '../support/controller';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';
import { addressOf } from '../support/page-objects/timeline-page';

const ROTATING = 'Rotating the CI token';
const CLAIM_NOTE = 'Pilot rotates it under the standing grant.';
const CUT_OVER_PATH = '/work/Example/cut-over.md';
// The pass's claim, as it writes it on the action (design 3 §6.4).
const CUT_OVER = `# The cut-over

\`\`\`action id=A1
answer: Pilot does it
by: agent
at: 2026-10-20T09:00:00Z
note: ${CLAIM_NOTE}
\`\`\`

\`\`\`decision id=D1
options:
  - Friday
  - Monday
\`\`\`
`;

interface Fixtures {
  people: People;
  projects: Projects;
  controller: Controller;
}

/**
 * The cut-over, registered by a work item's run in a project of the signed-in person's, read at the
 * run's end, its action A1 claimed, and the work item that does it placed; answers their ids.
 */
async function claimed({ people, projects, controller }: Fixtures) {
  const me = await people.signIn();
  const project = await projects.make({ name: makeUnique('Claimed'), members: [me.handle!] });
  const work = await projects.startWork(project, { title: 'Planning the cut-over', brief: 'Plan the cut-over.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  const { id: environment } = await projects.environment(project, work);
  await controller.putFile(environment, CUT_OVER_PATH, CUT_OVER);
  const document = await projects.register(work, CUT_OVER_PATH);
  await controller.finish(environment, 'claude-1');
  await expect.poll(async () => (await projects.item(project, document)).awaiting_read).toBe(false);
  const rotating = await projects.startWork(project, {
    title: ROTATING,
    brief: 'Rotate the CI token.',
    cwd: '/work/Example',
    claims: [`${document}/A1`],
  });
  return { project, document, rotating };
}

test.describe('A claimed action', () => {
  test('reads “Pilot does it” with its note and links the work item that does it, inline and in the overlay, open with a person’s controls; Send answers waits on it', async ({
    people,
    projects,
    controller,
    timeline,
    overlay,
    page,
  }) => {
    const { project, document, rotating } = await claimed({ people, projects, controller });
    await timeline.open(project);

    const item = timeline.item(document);
    const action = item.blockAt('A1');
    await expect(action.root).toHaveClass(/\bopen\b/);
    await expect(action.claim).toContainText('Pilot does it');
    await expect(action.claimWork).toHaveText(ROTATING);
    await expect(action.note).toHaveText(CLAIM_NOTE);
    await expect(action.answered).toHaveCount(0);
    await expect(action.said).toHaveCount(0);
    await expect(action.paste).toBeVisible();
    await expect(action.done).toBeEnabled();
    await expect(item.segment('A1')).not.toHaveClass(/\bdone\b/);
    await expect(item.unsent).toHaveCount(0);
    await item.blockAt('D1').option('Friday').click();
    await expect(item.blockAt('D1').answered).toBeVisible();
    await expect(item.send).toBeDisabled();

    await action.claimWork.click();
    await expect(page).toHaveURL(addressOf(project, rotating));

    await overlay.open(project, document);
    const inOverlay = overlay.blockAt('A1');
    await expect(inOverlay.claimWork).toHaveText(ROTATING);
    await expect(inOverlay.done).toBeEnabled();
    await expect(overlay.send).toBeDisabled();
    await inOverlay.claimWork.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(addressOf(project, rotating));
  });

  test('a person’s Done marks it done as any action’s, the claim gone, and the document’s answers can be sent', async ({
    people,
    projects,
    controller,
    timeline,
  }) => {
    const { project, document } = await claimed({ people, projects, controller });
    await timeline.open(project);

    const item = timeline.item(document);
    const action = item.blockAt('A1');
    await action.paste.fill('Rotated by hand.');
    await action.done.click();
    await expect(action.answered).toBeVisible();
    await expect(action.claim).toHaveCount(0);
    await expect(action.said.locator('.said')).toHaveText('Done');
    await expect(action.note).toHaveText('Rotated by hand.');
    await expect(item.unsent).toBeVisible();
    const done = (await projects.item(project, document)).body!.flatMap((part) => (part.type === 'block' && part.block.id === 'A1' ? [part.block] : []));
    expect(done.map((block) => [block.claim, block.by?.kind, block.note])).toEqual([[null, 'person', 'Rotated by hand.']]);

    await item.blockAt('D1').option('Monday').click();
    await expect(item.send).toBeEnabled();
    await item.send.click();
    await expect(item.root).toHaveAttribute('data-state', 'done');
  });
});

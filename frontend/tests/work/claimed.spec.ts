/**
 * An action of a registered document Pilot claimed (F21.6): open until its Done, Pilot's, its block
 * reading "Pilot does it" with the claim's note and a link to the work item the claim names, inline
 * and in the overlay, over a person's controls; the document's *Send answers* waits on it, and with
 * every other block answered, the document is Pilot's line, "Doing it" going to that work item
 * (F13.7), and opened it reads only under the gold strip, which links that work item and offers
 * *Stop and take over*, the take-over stopping that work; while the run doing it waits on the
 * person's answer to a document it registered, the strip links that document instead, with no Stop
 * (F28.9). Once the
 * work doing it is stopped, the action is the person's again, and their Done marks it done as any
 * action's Done, the claim gone; while that work is in flight the server takes no Done on it (DB
 * 295).
 */

import { test, expect } from '../support/fixtures';
import type { Chats } from '../support/chats';
import type { Controller } from '../support/controller';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';
import { documentAddress } from '../support/page-objects/overlay-page';
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
const ASK_PATH = '/work/Example/which-token.md';
const ASK_TITLE = 'Which token goes first?';
// What the work doing the action asks the person before it goes on.
const ASK = `# ${ASK_TITLE}\n\n\`\`\`question id=Q1\n\`\`\`\n`;

interface Fixtures {
  people: People;
  projects: Projects;
  controller: Controller;
  chats: Chats;
}

/**
 * The cut-over, registered by a work item's run in a project of the signed-in person's, read at the
 * run's end, the pass after it ended, its action A1 claimed, and the work item that does it placed;
 * answers their ids.
 */
async function claimed({ people, projects, controller, chats }: Fixtures) {
  const me = await people.signIn();
  const project = await projects.make({ name: makeUnique('Claimed'), members: [me.handle!] });
  const work = await projects.startWork(project, { title: 'Planning the cut-over', brief: 'Plan the cut-over.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  const { id: environment } = await projects.environment(project, work);
  await controller.putFile(environment, CUT_OVER_PATH, CUT_OVER);
  const document = await projects.register(work, CUT_OVER_PATH);
  const passed = await chats.passing(project);
  await controller.finish(environment, 'claude-1');
  await expect.poll(async () => (await projects.item(project, document)).awaiting_read).toBe(false);
  await passed();
  const rotating = await projects.startWork(project, {
    title: ROTATING,
    brief: 'Rotate the CI token.',
    cwd: '/work/Example',
    claims: [`${document}/A1`],
  });
  return { project, document, rotating };
}

test.describe('A claimed action', () => {
  test('reads “Pilot does it” with its note and links the work item that does it, inline, open with a person’s controls; Send answers waits on it, and with the other block answered the document is Pilot’s line, “Doing it” going to that work item, and opened it reads only under the strip, which links that work item, with Stop and take over', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
    overlay,
    page,
  }) => {
    const { project, document, rotating } = await claimed({ people, projects, controller, chats });
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
    await expect(action.claimWork).toHaveAttribute('href', addressOf(project, rotating));

    // The one block it leaves open held by the work doing it, the document is Pilot's.
    await item.blockAt('D1').option('Friday').click();
    await expect(item.root).toHaveAttribute('data-state', 'pilots');
    await expect(item.pilots.root).toHaveText('Doing it');
    await expect(item.pilots.root).toHaveAttribute('title', `Go to the work item: ${ROTATING}`);
    await expect(item.pilots.pulse).toBeVisible();
    await expect(item.open).toBeVisible();
    await item.pilots.root.click();
    await expect(page).toHaveURL(addressOf(project, rotating));

    await overlay.open(project, document);
    await expect(overlay.strip.root).toHaveAttribute('data-doing', 'doing');
    await expect(overlay.strip.text).toHaveText(`Pilot does what is open here in ${ROTATING}; its Done comes with the result.`);
    await expect(overlay.strip.link).toHaveAttribute('href', addressOf(project, rotating));
    await expect(overlay.strip.stop).toBeEnabled();
    const inOverlay = overlay.blockAt('A1');
    await expect(inOverlay.claimWork).toHaveText(ROTATING);
    await expect(inOverlay.paste).toBeDisabled();
    await expect(inOverlay.done).toBeDisabled();
    await expect(overlay.foot).toHaveCount(0);
    await inOverlay.claimWork.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(addressOf(project, rotating));
  });

  test('opened while the work doing it runs, Stop and take over on its strip stops that work, and the action is the person’s, live, its Done marking it done', async ({
    people,
    projects,
    controller,
    chats,
    overlay,
    deploymentSse,
  }) => {
    const { project, document, rotating } = await claimed({ people, projects, controller, chats });
    await projects.answer(document, 'D1', 'Friday');
    await overlay.open(project, document);
    await deploymentSse.ensureConnected();
    await expect(overlay.strip.root).toHaveAttribute('data-doing', 'doing');
    const action = overlay.blockAt('A1');
    await expect(action.done).toBeDisabled();

    await overlay.strip.stop.click();
    await expect(overlay.strip.root).toHaveCount(0);
    await expect(action.done).toBeEnabled();
    expect((await projects.work(project, rotating)).state).toBe('stopped');
    await action.paste.fill('Rotated by hand.');
    await action.done.click();
    await expect(action.answered).toBeVisible();
    await expect(overlay.send).toBeEnabled();
  });

  test('while the run doing it waits on the person’s answer to a document it registered, its document opened says so on the strip and links that document, with no Stop', async ({
    people,
    projects,
    controller,
    chats,
    overlay,
    page,
  }) => {
    const { project, document, rotating } = await claimed({ people, projects, controller, chats });
    await projects.answer(document, 'D1', 'Friday');
    await expect.poll(async () => (await projects.work(project, rotating)).state).toBe('running');
    const { id: environment } = await projects.environment(project, rotating);
    let session = '';
    await expect
      .poll(async () => {
        session = (await controller.sessionViews(environment)).find((each) => each.working)?.name ?? '';
        return session;
      })
      .not.toBe('');
    await controller.putFile(environment, ASK_PATH, ASK);
    const asking = await projects.register(rotating, ASK_PATH);
    const passed = await chats.passing(project);
    await controller.finish(environment, session);
    await expect.poll(async () => (await projects.item(project, asking)).awaiting_read).toBe(false);
    await passed();
    await expect.poll(async () => (await projects.item(project, document)).pilots_work?.doing).toBe('waiting_on_answer');

    await overlay.open(project, document);
    await expect(overlay.strip.root).toHaveAttribute('data-doing', 'waiting_on_answer');
    await expect(overlay.strip.text).toHaveText(`Pilot waits on your answer to ${ASK_TITLE} before it goes on with what is open here.`);
    await expect(overlay.strip.stop).toHaveCount(0);
    await expect(overlay.blockAt('A1').done).toBeDisabled();
    await overlay.strip.link.click();
    await expect(page).toHaveURL(documentAddress(project, asking));
    await expect(overlay.title).toHaveText(ASK_TITLE);
    await expect(overlay.strip.root).toHaveCount(0);
  });

  test('once the work doing it is stopped, a person’s Done marks it done as any action’s, the claim gone, and the document’s answers can be sent', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
  }) => {
    const { project, document, rotating } = await claimed({ people, projects, controller, chats });
    await projects.stop(rotating);
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

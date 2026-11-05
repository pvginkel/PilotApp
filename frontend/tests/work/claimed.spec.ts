/**
 * An action of a registered document Pilot claimed (F21.6), Pilot's while the work doing it is in
 * flight, running or queued at the gate: inline, its section is its held line (F31.7), "Doing it"
 * going to that work item, the claim's note under it and its segment in the plan donut's in-progress
 * colour, and opened its controls take nothing, *Send answers* waiting on it; with every other block
 * answered, the document is Pilot's line, "Doing it" going to that work item (F13.7), and opened it
 * reads only under the gold strip, its blocks drawn whole, which links that work item and offers
 * *Stop and take over*, the take-over stopping that work; while the run doing it waits on the
 * person's answer to a document it registered, the strip links that document instead, with no Stop,
 * and that document's Cancel ends the run, the action the person's again at once (F28.9). Once the
 * work doing it fails or is stopped, the action is the person's again, live, unfolded with its
 * controls, its head saying Pilot's work left it undone, and their Done marks it done as any
 * action's Done, the claim gone; while that work is in flight the server takes no Done on it (DB
 * 295). A block a work item researches is its held line too, "Researching" (F52.3).
 */

import type { Locator } from '@playwright/test';
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
const CUT_OVER_TITLE = 'The cut-over';
// A1's own section's heading, which a Cancel's button names it by.
const TOKEN = 'The CI token';
// A decision with a recommendation that no work item holds.
const THE_HOUR = `
## The hour

\`\`\`decision id=D2
options:
  - Morning
  - Evening
recommend: Morning
\`\`\`
`;
// The pass's claim, as it writes it on the action (design 3 §6.4); `recommended`, D1 recommends a day
// and a second decision after it, which recommends an hour, waits on the person too.
const cutOver = (heading: string, recommended = false) => `# ${CUT_OVER_TITLE}

## ${heading}

\`\`\`action id=A1
answer: Pilot does it
by: agent
at: 2026-10-20T09:00:00Z
note: ${CLAIM_NOTE}
\`\`\`

## The day

\`\`\`decision id=D1
options:
  - Friday
  - Monday
${recommended ? 'recommend: Friday\n' : ''}\`\`\`
${recommended ? THE_HOUR : ''}`;
// A one-ask document: its one action, under the title alone, claimed by the pass.
const ROLL_OUT = `# The roll-out

\`\`\`action id=A1
answer: Pilot does it
by: agent
at: 2026-10-20T09:00:00Z
note: ${CLAIM_NOTE}
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
 * A document of `text`, the cut-over or another whose action A1 the pass claimed, registered by a work
 * item's run in a project of the signed-in person's, read at the run's end, and the pass after it
 * ended; answers their ids.
 */
async function registered({ people, projects, controller, chats }: Fixtures, text: string) {
  const me = await people.signIn();
  const project = await projects.make({ name: makeUnique('Claimed'), members: [me.handle!] });
  const work = await projects.startWork(project, { title: 'Planning the cut-over', brief: 'Plan the cut-over.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  const { id: environment } = await projects.environment(project, work);
  await controller.putFile(environment, CUT_OVER_PATH, text);
  const document = await projects.register(work, CUT_OVER_PATH);
  const passed = await chats.passing(project);
  await controller.finish(environment, 'claude-1');
  await expect.poll(async () => (await projects.item(project, document)).awaiting_read).toBe(false);
  await passed();
  return { project, document };
}

/**
 * The cut-over, A1 under `heading`, or the document of `text`, registered, and the work item that
 * does A1 placed, the project paused first where `paused` says so, which holds that work at the gate;
 * answers their ids.
 */
async function claimed(fixtures: Fixtures, { heading = TOKEN, paused = false, text = cutOver(heading) } = {}) {
  const { projects } = fixtures;
  const { project, document } = await registered(fixtures, text);
  if (paused) await projects.transition(project, 'paused');
  const rotating = await projects.startWork(project, {
    title: ROTATING,
    brief: 'Rotate the CI token.',
    cwd: '/work/Example',
    claims: [`${document}/A1`],
  });
  return { project, document, rotating };
}

/** The environment of a work item's running session, and that session's name. */
async function turnOf({ projects, controller }: Fixtures, project: string, work: string) {
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  const { id: environment } = await projects.environment(project, work);
  let session = '';
  await expect
    .poll(async () => {
      session = (await controller.sessionViews(environment)).find((each) => each.working)?.name ?? '';
      return session;
    })
    .not.toBe('');
  return { environment, session };
}

/** A segment's colour as the page draws it. */
const colourOf = (segment: Locator) => segment.evaluate((each) => getComputedStyle(each).backgroundColor);

/**
 * The cut-over claimed, D1 answered, and the work doing A1 registering a question to the person at
 * its turn's end, read, the pass after it ended, so that the run waits on their answer; answers the
 * ids, the question's `asking`.
 */
async function waiting(fixtures: Fixtures, heading = TOKEN) {
  const { projects, controller, chats } = fixtures;
  const { project, document, rotating } = await claimed(fixtures, { heading });
  await projects.answer(document, 'D1', 'Friday');
  const { environment, session } = await turnOf(fixtures, project, rotating);
  await controller.putFile(environment, ASK_PATH, ASK);
  const asking = await projects.register(rotating, ASK_PATH);
  const passed = await chats.passing(project);
  await controller.finish(environment, session);
  await expect.poll(async () => (await projects.item(project, asking)).awaiting_read).toBe(false);
  await passed();
  await expect.poll(async () => (await projects.item(project, document)).pilots_work?.doing).toBe('waiting_on_answer');
  return { project, document, asking };
}

test.describe('A claimed action', () => {
  test('is its section’s held line inline, “Doing it” going to the work item that does it, the claim’s note under it and its segment in progress, its controls taking nothing once opened and Send answers waiting on it; with the other block answered the document is Pilot’s line, “Doing it” going to that work item, and opened it reads only under the strip, its blocks drawn whole, which links that work item, with Stop and take over', async ({
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
    await expect(action.root).toHaveClass(/\bheld\b/);
    await expect(action.held.heading).toHaveText(TOKEN);
    await expect(action.held.pilots).toHaveText('Doing it');
    await expect(action.held.pilots).toHaveAttribute('data-doing', 'doing');
    await expect(action.held.pilots).toHaveAttribute('title', `Go to the work item: ${ROTATING}`);
    await expect(action.held.pilots.locator('.avatar')).toHaveCount(0);
    await expect(action.held.pulse).toBeVisible();
    await expect(action.note).toHaveText(CLAIM_NOTE);
    await expect(action.head).toHaveCount(0);
    await expect(action.claim).toHaveCount(0);
    await expect(action.paste).toHaveCount(0);
    await expect(item.segment('A1')).toHaveClass(/\bheld\b/);
    await expect(item.segment('A1')).toHaveAttribute('title', `${TOKEN} · Pilot is working on it`);
    expect(await colourOf(item.segment('A1'))).not.toBe(await colourOf(item.segment('D1')));
    await expect(item.unsent).toHaveCount(0);
    await expect(item.send).toBeDisabled();

    await action.held.heading.click();
    await expect(action.held.toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(action.held.body).toBeVisible();
    await expect(action.paste).toBeDisabled();
    await expect(action.done).toBeDisabled();
    await action.held.toggle.click();
    await expect(action.held.body).toHaveCount(0);
    await action.held.pilots.click();
    await expect(page).toHaveURL(addressOf(project, rotating));
    await expect(action.held.body).toHaveCount(0);

    // The one block it leaves open held by the work doing it, the document is Pilot's.
    await item.blockAt('D1').option('Friday').click();
    await expect(item.root).toHaveAttribute('data-state', 'pilots');
    await expect(item.pilots.root).toHaveText('Doing it');
    await expect(item.pilots.root).toHaveAttribute('title', `Go to the work item: ${ROTATING}`);
    await expect(item.pilots.pulse).toBeVisible();
    await expect(item.open).toBeVisible();

    await overlay.open(project, document);
    await expect(overlay.strip.root).toHaveAttribute('data-doing', 'doing');
    await expect(overlay.strip.text).toHaveText(`Pilot does what is open here in ${ROTATING}; its Done comes with the result.`);
    await expect(overlay.strip.link).toHaveAttribute('href', addressOf(project, rotating));
    await expect(overlay.strip.stop).toBeEnabled();
    const inOverlay = overlay.blockAt('A1');
    await expect(inOverlay.held.line).toHaveCount(0);
    await expect(inOverlay.claimWork).toHaveText(ROTATING);
    await expect(inOverlay.note).toHaveText(CLAIM_NOTE);
    await expect(inOverlay.paste).toBeDisabled();
    await expect(inOverlay.done).toBeDisabled();
    await expect(overlay.foot).toHaveCount(0);
    await inOverlay.claimWork.click();
    await expect(overlay.root).toHaveCount(0);
    await expect(page).toHaveURL(addressOf(project, rotating));
  });

  test('queued at the gate, the work doing it held by the pause, it is its held line, the dot pulsing, its controls taking nothing and its segment in progress; once that work is stopped it unfolds, live, with its controls, its head saying Pilot’s work left it undone', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
    deploymentSse,
  }) => {
    const { project, document, rotating } = await claimed({ people, projects, controller, chats }, { paused: true });
    await expect.poll(async () => (await projects.work(project, rotating)).state).toBe('held');
    await timeline.open(project);
    await deploymentSse.ensureConnected();

    const item = timeline.item(document);
    const action = item.blockAt('A1');
    await expect(action.held.pilots).toHaveAttribute('data-doing', 'doing');
    await expect(action.held.pulse).toBeVisible();
    await expect(item.segment('A1')).toHaveClass(/\bheld\b/);
    await action.held.toggle.click();
    await expect(action.paste).toBeDisabled();
    await expect(action.done).toBeDisabled();

    await projects.stop(rotating);
    await expect(action.held.line).toHaveCount(0);
    await expect(action.root).toHaveClass(/\bopen\b/);
    await expect(action.undone).toHaveText('Pilot’s work left it undone');
    await expect(action.undone).toHaveAttribute('title', `${ROTATING} ended without doing it: it is yours again`);
    await expect(action.claim).toHaveCount(0);
    await expect(action.paste).toBeEnabled();
    await expect(action.done).toBeEnabled();
    await expect(item.segment('A1')).not.toHaveClass(/\bheld\b/);
    expect(await colourOf(item.segment('A1'))).toBe(await colourOf(item.segment('D1')));
  });

  test('once the turn of the work doing it fails, it unfolds, live, with its controls, its head saying Pilot’s work left it undone, and the person’s Done closes it', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
    deploymentSse,
  }) => {
    const fixtures = { people, projects, controller, chats };
    const { project, document, rotating } = await claimed(fixtures);
    const { environment, session } = await turnOf(fixtures, project, rotating);
    await timeline.open(project);
    await deploymentSse.ensureConnected();
    const item = timeline.item(document);
    const action = item.blockAt('A1');
    await expect(action.held.line).toBeVisible();

    await controller.finish(environment, session, 'error', 'The model is overloaded.');
    await expect(action.undone).toBeVisible();
    await expect(action.held.line).toHaveCount(0);
    expect((await projects.work(project, rotating)).state).toBe('failed');
    await action.paste.fill('Rotated by hand.');
    await action.done.click();
    await expect(action.answered).toBeVisible();
    await expect(action.undone).toHaveCount(0);
    await expect(action.claim).toHaveCount(0);
  });

  test('opened while the work doing it runs, Stop and take over on its strip stops that work, and the action is the person’s, live, its head saying Pilot’s work left it undone, its Done marking it done', async ({
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
    await expect(action.undone).toBeVisible();
    expect((await projects.work(project, rotating)).state).toBe('stopped');
    await action.paste.fill('Rotated by hand.');
    await action.done.click();
    await expect(action.answered).toBeVisible();
    await expect(overlay.send).toBeEnabled();
  });

  test('while the run doing it waits on the person’s answer to a document it registered, its document opened says so on the strip and links that document, with no Stop; that document’s Cancel, saying it is part of the work on the first and naming the action, closes it, and the action is the person’s, live, its head saying Pilot’s work left it undone', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
    overlay,
    page,
  }) => {
    const { project, document, asking } = await waiting({ people, projects, controller, chats });

    await overlay.open(project, document);
    await expect(overlay.strip.root).toHaveAttribute('data-doing', 'waiting_on_answer');
    await expect(overlay.strip.text).toHaveText(`Pilot waits on your answer to ${ASK_TITLE} before it goes on with what is open here.`);
    await expect(overlay.strip.stop).toHaveCount(0);
    await expect(overlay.blockAt('A1').done).toBeDisabled();
    await overlay.strip.link.click();
    await expect(page).toHaveURL(documentAddress(project, asking));
    await expect(overlay.title).toHaveText(ASK_TITLE);
    await expect(overlay.strip.root).toHaveCount(0);

    await expect(overlay.cancel.line).toHaveText(`Pilot asks this as part of its work on ${CUT_OVER_TITLE}.`);
    await expect(overlay.cancel.links).toHaveAttribute('href', documentAddress(project, document));
    await expect(overlay.cancel.button).toHaveText(`Cancel and take back “${TOKEN}”`);
    await overlay.cancel.button.click();
    await expect(overlay.done).toBeVisible();
    await expect(overlay.cancel.button).toHaveCount(0);
    const cancelled = (await projects.item(project, asking)).done;
    expect([cancelled?.cause, cancelled?.undo]).toEqual(['cancelled', false]);

    await overlay.close.click();
    await expect(timeline.item(asking).root).toHaveAttribute('data-state', 'done');
    await expect(timeline.item(asking).undo).toHaveCount(0);
    const item = timeline.item(document);
    await expect(item.root).toHaveAttribute('data-state', 'open');
    const action = item.blockAt('A1');
    await expect(action.held.line).toHaveCount(0);
    await expect(action.undone).toBeVisible();
    await expect(action.done).toBeEnabled();
    await action.paste.fill('Rotated by hand.');
    await action.done.click();
    await expect(action.answered).toBeVisible();
    await expect(action.claim).toHaveCount(0);
  });

  test('once the work doing it is stopped, it unfolds with its controls, its head saying Pilot’s work left it undone, and a person’s Done marks it done as any action’s, the claim gone, and the document’s answers can be sent', async ({
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
    await expect(action.root).toHaveClass(/\bopen\b/);
    await expect(action.undone).toHaveText('Pilot’s work left it undone');
    await expect(action.claim).toHaveCount(0);
    await expect(action.said).toHaveCount(0);
    await expect(item.segment('A1')).not.toHaveClass(/\bheld\b/);
    await action.paste.fill('Rotated by hand.');
    await action.done.click();
    await expect(action.answered).toBeVisible();
    await expect(action.undone).toHaveCount(0);
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

  test('alone in its document, once the work doing it is stopped, its head says Pilot’s work left it undone, over its controls', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
  }) => {
    const { project, document, rotating } = await claimed({ people, projects, controller, chats }, { text: ROLL_OUT });
    await projects.stop(rotating);
    await timeline.open(project);

    const action = timeline.item(document).blockAt('A1');
    await expect(action.root).toHaveClass(/\bopen\b/);
    await expect(action.undone).toHaveText('Pilot’s work left it undone');
    await expect(action.undone).toHaveAttribute('title', `${ROTATING} ended without doing it: it is yours again`);
    await expect(action.done).toBeEnabled();
  });
});

test.describe('A researched block', () => {
  test('is its section’s held line, “Researching” going to the work item that checks its fact, its segment in progress and its controls taking nothing once opened, beside an action claimed for no work item, the person’s; with that action done and every other block recommended, Send answers waits on it', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
  }) => {
    const { project, document } = await registered({ people, projects, controller, chats }, cutOver(TOKEN, true));
    const checking = await projects.startWork(project, {
      title: 'Checking the release calendar',
      brief: 'Check which day the release calendar leaves free.',
      cwd: '/work/Example',
      researches: [`${document}/D1`],
    });
    await timeline.open(project);

    const item = timeline.item(document);
    await expect(item.root).toHaveAttribute('data-state', 'open');
    const day = item.blockAt('D1');
    await expect(day.held.heading).toHaveText('The day');
    await expect(day.held.pilots).toHaveText('Researching');
    await expect(day.held.pilots).toHaveAttribute('href', addressOf(project, checking));
    await expect(item.segment('D1')).toHaveClass(/\bheld\b/);
    await day.held.toggle.click();
    await expect(day.option('Friday')).toBeDisabled();
    await expect(day.option('Monday')).toBeDisabled();

    const action = item.blockAt('A1');
    await expect(action.held.line).toHaveCount(0);
    await expect(action.undone).toHaveCount(0);
    await expect(action.claim).toContainText('Pilot does it');
    await expect(action.done).toBeEnabled();

    // D1 and D2 recommended and A1 done, only D1's hold keeps Send from sending.
    await action.paste.fill('Rotated by hand.');
    await action.done.click();
    await expect(action.answered).toBeVisible();
    await expect(item.send).toBeDisabled();
    await expect(item.send).toHaveAttribute('title', 'Pilot is working on a block of it: send once Pilot is done');
  });
});

test.describe('A claimed action on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('while the run doing it waits on the person’s answer to a document it registered, that document’s Cancel names the action whole, its words wrapping inside the foot', async ({
    people,
    projects,
    controller,
    chats,
    overlay,
  }) => {
    const heading = 'Rotate the CI token on Jenkins and in GitHub Actions';
    const { project, asking } = await waiting({ people, projects, controller, chats }, heading);

    await overlay.open(project, asking);
    await expect(overlay.cancel.button).toHaveText(`Cancel and take back “${heading}”`);
    const foot = (await overlay.foot.boundingBox())!;
    const button = (await overlay.cancel.button.boundingBox())!;
    expect(button.x + button.width).toBeLessThanOrEqual(foot.x + foot.width);
    expect(await overlay.cancel.button.evaluate((each) => each.scrollWidth <= each.clientWidth)).toBe(true);
  });
});

/**
 * What the pre-ruling pass asked a registered document's writer, and the writer's reply (F52.2):
 * the overlay's box over the document's text, "Pilot asked the writer", its stamp and the reply's,
 * the questions from the asking on, each saying the reply is awaited while the clarification run
 * runs, and the reply joining them at its turn end, live, per block where it kept the headings asked
 * for and whole where it did not. Each asked block's head carries the mark, and no line under the
 * title says the writer was asked: on the timeline the mark opens the document at the box's
 * address, the box gone to and flashing, and in the overlay it goes to the box. A section the pass
 * settled on the reply is its line, with no mark, its note quoting the writer (F31.5). While the
 * clarification run runs, the document is Pilot's line, "Asking the writer" standing still with the pulse (F13.7), and opened it reads only,
 * under the gold strip saying so, with *Stop and take over* (F28.9). The run's continuation, placed while the
 * clarification run runs on the same conversation, waits for it: "Waiting for the run before it"
 * (DB 183). While Pilot asks the writer the document takes nothing from the app's controls (DB
 * 295), so its answers come through the project's chat, and Pilot's Done closes it.
 */

import { test, expect } from '../support/fixtures';
import type { Chats } from '../support/chats';
import type { Controller } from '../support/controller';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';
import { clarificationAddress, documentAddress } from '../support/page-objects/overlay-page';

const ZONE = 'Europe/Amsterdam';
test.use({ timezoneId: ZONE });
const stamp = (at: string) => new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: ZONE }).format(new Date(at));

// An invented line in `claude`'s shape (backend/tests/fixtures/raw/), naming its conversation, as
// every line `claude` prints does, so that the runs after it resume it.
const CONVERSATION = '4b8e2d17-9c3f-4a61-b5e0-7d2a9f1c6e38';
const text = (id: string, words: string) =>
  JSON.stringify({
    type: 'assistant',
    message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] },
    parent_tool_use_id: null,
    session_id: CONVERSATION,
  });

/** A decision block of the DSL, its options as given. */
const decision = (id: string, ...options: string[]) =>
  ['```decision id=' + id, 'options:', ...options.map((option) => `  - ${option}`), '```', ''].join('\n');
const KIT_PATH = '/work/Example/kit.md';
const KIT = `# The kit\n\n${decision('D1', 'Dome', 'Tunnel')}\n${decision('D2', 'Gas', 'Wood')}\n${decision('D3', 'Two', 'Four')}\n${decision('D4', 'Rope', 'Chain')}`;
// Over 150 words of its own, so that it leaves a card.
const ROUTE_PATH = '/work/Example/route.md';
const ROUTE = `# The route\n\n${'We walk the north shore to the ridge and camp below it. '.repeat(16)}\n\n${decision('D1', 'Shore', 'Ridge')}\n${decision('D2', 'Day', 'Night')}`;

const STOVE = 'Which stove does “gas” mean?';
const CHAIN = 'Does “chain” mean the lock or the tow chain?';
const SPLIT = '## D2\nThe camping stove, not the van’s.\n\n## D4\nThe tow chain.';
const SHORE = 'Is the shore path open in spring?';
const WHOLE = 'It opens in April; only the ridge path stays shut until May.';
// Each block in a section of its own, so that the one Pilot settles is its section's line.
const STOVES_PATH = '/work/Example/stoves.md';
const STOVES = `# The stoves\n\n## Which stove?\n\n${decision('D1', 'Gas', 'Wood')}\n## How many?\n\n${decision('D2', 'One', 'Two')}`;
const CAMPING = 'The camping stove, not the van’s.';
const QUOTED = `The writer says “${CAMPING}”`;
// The pass after the reply settles D1 on the writer's words.
const SETTLED = STOVES.replace(
  decision('D1', 'Gas', 'Wood'),
  ['```decision id=D1', 'options:', '  - Gas', '  - Wood', 'answer: Gas', 'by: agent', 'at: 2026-11-03T09:00:00Z', `note: ${QUOTED}`, '```', ''].join('\n'),
);

interface Fixtures {
  people: People;
  projects: Projects;
  controller: Controller;
  chats: Chats;
}

/**
 * A work item's run in a project of the signed-in person's, which wrote and registered the
 * documents at `files` in its environment and ended, each document read and the pass after it
 * ended; answers their ids. With `session`, the project has a session of its own, through which
 * Pilot saves a document.
 */
async function written({ people, projects, controller, chats }: Fixtures, files: [string, string][], { session = false } = {}) {
  const me = await people.signIn();
  const spec = { name: makeUnique('Clarified'), members: [me.handle!] };
  const project = session ? await projects.makeWithSession(spec) : await projects.make(spec);
  const work = await projects.startWork(project, { title: 'Packing the camp', brief: 'Pack the camp.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  const { id: environment } = await projects.environment(project, work);
  const documents: string[] = [];
  for (const [path, content] of files) {
    await controller.putFile(environment, path, content);
    documents.push(await projects.register(work, path));
  }
  const passed = await chats.passing(project);
  await controller.play(environment, 'claude-1', [text('wrote', 'The kit and the route are written.')]);
  await controller.finish(environment, 'claude-1');
  for (const document of documents) await expect.poll(async () => (await projects.item(project, document)).awaiting_read).toBe(false);
  await passed();
  return { project, work, environment, documents, handle: me.handle! };
}

test.describe('Pilot asking the writer', () => {
  test('shows its questions and the reply in a box over the document in the overlay, per block where the reply kept the headings asked for and whole where it did not; each asked block’s head carries the mark, which opens the document at the box from the timeline and goes to it in the overlay, and no line under the title says so', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
    overlay,
    page,
  }) => {
    const {
      project,
      documents: [kit, route],
    } = await written({ people, projects, controller, chats }, [
      [KIT_PATH, KIT],
      [ROUTE_PATH, ROUTE],
    ]);
    await projects.askWriter(kit, [
      { block: 'D4', question: CHAIN },
      { block: 'D2', question: STOVE },
    ]);
    await projects.clarify(kit, SPLIT);
    await projects.askWriter(route, [{ block: 'D1', question: SHORE }]);
    await projects.clarify(route, WHOLE);

    await timeline.open(project);
    const inline = timeline.item(kit);
    await expect(inline.blockAt('D2').writerAsked).toHaveText('Pilot asked the writer');
    await expect(inline.blockAt('D4').writerAsked).toHaveText('Pilot asked the writer');
    await expect(inline.blockAt('D4').writerAsked).toHaveAttribute('href', clarificationAddress(project, kit));
    await expect(inline.blockAt('D1').writerAsked).toHaveCount(0);
    await expect(inline.blockAt('D3').writerAsked).toHaveCount(0);
    await expect(inline.writerAsked).toHaveCount(0);
    await expect(inline.root).not.toContainText('Pilot asked the writer about');

    const [asked] = (await projects.item(project, kit)).clarifications;
    await inline.blockAt('D4').writerAsked.click();
    await expect(page).toHaveURL(clarificationAddress(project, kit));
    await expect(overlay.clarificationBox).toHaveClass(/\bflash\b/);
    await expect(overlay.clarificationBox).toBeInViewport();
    await expect(overlay.clarifications).toHaveCount(1);
    const split = overlay.clarification();
    await expect(split.head).toHaveText(`Pilot asked the writer · ${stamp(asked.asked_at)} · replied ${stamp(asked.replied_at!)}`);
    await expect(split.questions.getByTestId('overlay.clarification.block')).toHaveText(['D2', 'D4']);
    await expect(split.question('D2').text).toHaveText(STOVE);
    await expect(split.question('D2').reply).toHaveText('The camping stove, not the van’s.');
    await expect(split.question('D4').text).toHaveText(CHAIN);
    await expect(split.question('D4').reply).toHaveText('The tow chain.');
    await expect(split.reply).toHaveCount(0);
    await expect(split.questions.getByTestId('overlay.clarification.awaited')).toHaveCount(0);
    await expect(overlay.blockAt('D2').writerAsked).toHaveText('Pilot asked the writer');
    await expect(overlay.blockAt('D1').writerAsked).toHaveCount(0);

    // Short enough a window that the route's text runs past the overlay's body.
    await page.setViewportSize({ width: 1280, height: 480 });
    await overlay.open(project, route);
    const whole = overlay.clarification();
    await expect(whole.question('D1').text).toHaveText(SHORE);
    await expect(whole.question('D1').reply).toHaveCount(0);
    await expect(whole.reply).toHaveText(WHOLE);
    await expect(whole.replies).toHaveCount(1);
    await expect(overlay.blockAt('D2').writerAsked).toHaveCount(0);
    const shore = overlay.blockAt('D1').writerAsked;
    await expect(shore).toHaveText('Pilot asked the writer');
    await expect(shore).not.toHaveAttribute('href');
    await overlay.body.evaluate((body) => body.scrollTo({ top: body.scrollHeight }));
    await expect(overlay.clarificationBox).not.toBeInViewport();
    await shore.click();
    await expect(overlay.clarificationBox).toBeInViewport();
    await expect(overlay.clarificationBox).toHaveClass(/\bflash\b/);
    await expect(page).toHaveURL(documentAddress(project, route));
  });

  test('a section the pass after the writer’s reply settled is its line, with no mark of the writer asked, its note quoting the writer; opened, its block’s head carries the mark', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
  }) => {
    const {
      project,
      documents: [stoves],
    } = await written({ people, projects, controller, chats }, [[STOVES_PATH, STOVES]], { session: true });
    await projects.askWriter(stoves, [{ block: 'D1', question: STOVE }]);
    await projects.clarify(stoves, CAMPING);
    expect(await projects.save(stoves, SETTLED)).toEqual({ held: false, faults: [] });
    await projects.endTurn(project);

    await timeline.open(project);
    const item = timeline.item(stoves);
    const line = item.settledLine('D1');
    await expect(line.heading).toHaveText('Which stove?');
    await expect(line.answer).toHaveText('Gas');
    await expect(line.note).toHaveText(QUOTED);
    await expect(line.root).not.toContainText('Pilot asked the writer');
    await expect(item.root.getByTestId('timeline.block.writer-asked')).toHaveCount(0);
    await expect(item.writerAsked).toHaveCount(0);

    await line.root.click();
    await expect(item.blockAt('D1').writerAsked).toHaveText('Pilot asked the writer');
  });

  test('holds the questions, the reply awaited, until the clarification run’s turn ends, the reply joining them live, the document Pilot’s line meanwhile, “Asking the writer” going nowhere, and read-only under the strip with Stop and take over; the run’s continuation, placed meanwhile through the chat, reads “Waiting for the run before it” and starts after it', async ({
    people,
    projects,
    controller,
    chats,
    timeline,
    overlay,
    deploymentSse,
  }) => {
    const {
      project,
      work,
      environment,
      documents: [kit],
      handle,
    } = await written({ people, projects, controller, chats }, [[KIT_PATH, KIT]]);
    await projects.askWriter(kit, [{ block: 'D2', question: STOVE }]);
    const clarifying = await projects.clarify(kit);
    await expect.poll(async () => (await projects.work(project, clarifying)).state).toBe('running');
    const [run] = (await controller.sessions(environment)).filter((name) => name !== 'claude-1');

    await overlay.open(project, kit);
    await deploymentSse.ensureConnected();
    const section = overlay.clarification();
    await expect(section.question('D2').text).toHaveText(STOVE);
    await expect(section.question('D2').awaited).toHaveText('Awaiting the writer’s reply');
    await expect(section.replies).toHaveCount(0);
    await expect(section.replied).toHaveCount(0);
    await expect(overlay.strip.root).toHaveAttribute('data-doing', 'asking_writer');
    await expect(overlay.strip.text).toHaveText(
      'Pilot asked the writer about this document and waits for the reply, then goes over it again.',
    );
    await expect(overlay.strip.stop).toBeEnabled();
    await expect(overlay.blockAt('D1').option('Dome')).toBeDisabled();
    await expect(overlay.foot).toHaveCount(0);
    await expect(timeline.item(clarifying).title).toHaveText('Clarify kit.md');
    const line = timeline.item(kit);
    await expect(line.root).toHaveAttribute('data-state', 'pilots');
    await expect(line.pilots.root).toHaveText('Asking the writer');
    await expect(line.pilots.root).not.toHaveAttribute('href');
    await expect(line.pilots.pulse).toHaveCount(1);

    await chats.start(project, 'Answer the kit for me.');
    for (const [block, answer] of [
      ['D1', 'Dome'],
      ['D2', 'Gas'],
      ['D3', 'Two'],
      ['D4', 'Rope'],
    ]) {
      await chats.answer(project, `${kit}/${block}`, answer, handle);
    }
    await projects.doneByPilot(kit);
    // The run's continuation: its other work item but the clarification run, Pilot's own jobs aside.
    const others = async () =>
      (await projects.timeline(project)).items.filter(
        (item) => item.kind === 'work' && ![work, clarifying].includes(item.id) && !item.work?.pilots_own,
      );
    await expect.poll(async () => (await others()).length).toBe(1);
    const continuation = (await others())[0].id;
    await expect.poll(async () => (await projects.work(project, continuation)).state).toBe('held');
    const held = timeline.item(continuation).work;
    await expect(held.line).toHaveAttribute('data-state', 'held');
    await expect(held.cue).toHaveText('Waiting for the run before it');

    await controller.finish(environment, run, 'success', '## D2\nThe camping stove.');
    await expect(section.question('D2').reply).toHaveText('The camping stove.');
    await expect(section.question('D2').awaited).toHaveCount(0);
    await expect(section.replied).toBeVisible();
    await expect(section.reply).toHaveCount(0);
    await expect.poll(async () => (await projects.work(project, continuation)).state).toBe('running');
    await expect(held.line).not.toHaveAttribute('data-state', 'held');
  });
});

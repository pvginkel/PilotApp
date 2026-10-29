/**
 * What the pre-ruling pass asked a registered document's writer, and the writer's reply (F52.2):
 * the overlay's section over the document's text, "Pilot asked the writer · <stamp>", the questions
 * from the asking on and the reply joining them at the clarification run's turn end, live, per block
 * where it kept the headings asked for and whole where it did not; each asked block's head says so,
 * and the document's line on the timeline stays. The run's continuation, placed while the
 * clarification run runs on the same conversation, waits for it: "Waiting for the run before it"
 * (DB 183).
 */

import { test, expect } from '../support/fixtures';
import type { Controller } from '../support/controller';
import { makeUnique } from '../support/helpers';
import type { People } from '../support/people';
import type { Projects } from '../support/projects';

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

interface Fixtures {
  people: People;
  projects: Projects;
  controller: Controller;
}

/**
 * A work item's run in a project of the signed-in person's, which wrote and registered the
 * documents at `files` in its environment and ended, each document read; answers their ids.
 */
async function written({ people, projects, controller }: Fixtures, files: [string, string][]) {
  const me = await people.signIn();
  const project = await projects.make({ name: makeUnique('Clarified'), members: [me.handle!] });
  const work = await projects.startWork(project, { title: 'Packing the camp', brief: 'Pack the camp.', cwd: '/work/Example' });
  await expect.poll(async () => (await projects.work(project, work)).state).toBe('running');
  const { id: environment } = await projects.environment(project, work);
  const documents: string[] = [];
  for (const [path, content] of files) {
    await controller.putFile(environment, path, content);
    documents.push(await projects.register(work, path));
  }
  await controller.play(environment, 'claude-1', [text('wrote', 'The kit and the route are written.')]);
  await controller.finish(environment, 'claude-1');
  for (const document of documents) await expect.poll(async () => (await projects.item(project, document)).awaiting_read).toBe(false);
  return { project, work, environment, documents };
}

test.describe('Pilot asking the writer', () => {
  test('shows its questions and the reply over the document in the overlay, per block where the reply kept the headings asked for and whole where it did not; each asked block’s head says so, and the timeline’s line stays', async ({
    people,
    projects,
    controller,
    timeline,
    overlay,
  }) => {
    const {
      project,
      documents: [kit, route],
    } = await written({ people, projects, controller }, [
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
    await expect(inline.writerAsked).toHaveText('Pilot asked the writer about D2 and D4');
    await expect(inline.blockAt('D2').writerAsked).toHaveText('Pilot asked the writer');
    await expect(inline.blockAt('D4').writerAsked).toHaveText('Pilot asked the writer');
    await expect(inline.blockAt('D1').writerAsked).toHaveCount(0);
    await expect(inline.blockAt('D3').writerAsked).toHaveCount(0);

    const [asked] = (await projects.item(project, kit)).clarifications;
    await overlay.open(project, kit);
    await expect(overlay.clarifications).toHaveCount(1);
    const split = overlay.clarification();
    await expect(split.head).toHaveText(`Pilot asked the writer · ${stamp(asked.asked_at)}`);
    await expect(split.questions.getByTestId('overlay.clarification.block')).toHaveText(['D2', 'D4']);
    await expect(split.question('D2').text).toHaveText(STOVE);
    await expect(split.question('D2').reply).toHaveText('The camping stove, not the van’s.');
    await expect(split.question('D4').text).toHaveText(CHAIN);
    await expect(split.question('D4').reply).toHaveText('The tow chain.');
    await expect(split.reply).toHaveCount(0);
    await expect(overlay.blockAt('D2').writerAsked).toHaveText('Pilot asked the writer');
    await expect(overlay.blockAt('D1').writerAsked).toHaveCount(0);

    await overlay.open(project, route);
    const whole = overlay.clarification();
    await expect(whole.question('D1').text).toHaveText(SHORE);
    await expect(whole.question('D1').reply).toHaveCount(0);
    await expect(whole.reply).toHaveText(WHOLE);
    await expect(whole.replies).toHaveCount(1);
    await expect(overlay.blockAt('D1').writerAsked).toHaveText('Pilot asked the writer');
    await expect(overlay.blockAt('D2').writerAsked).toHaveCount(0);
  });

  test('holds the questions alone until the clarification run’s turn ends, the reply joining them live; the run’s continuation, placed meanwhile, reads “Waiting for the run before it” and starts after it', async ({
    people,
    projects,
    controller,
    timeline,
    overlay,
    deploymentSse,
  }) => {
    const {
      project,
      work,
      environment,
      documents: [kit],
    } = await written({ people, projects, controller }, [[KIT_PATH, KIT]]);
    await projects.askWriter(kit, [{ block: 'D2', question: STOVE }]);
    const clarifying = await projects.clarify(kit);
    await expect.poll(async () => (await projects.work(project, clarifying)).state).toBe('running');
    const [run] = (await controller.sessions(environment)).filter((name) => name !== 'claude-1');

    await overlay.open(project, kit);
    await deploymentSse.ensureConnected();
    const section = overlay.clarification();
    await expect(section.question('D2').text).toHaveText(STOVE);
    await expect(section.replies).toHaveCount(0);
    await expect(timeline.item(clarifying).title).toHaveText(`Clarify ${KIT_PATH}`);

    for (const [block, answer] of [
      ['D1', 'Dome'],
      ['D2', 'Gas'],
      ['D3', 'Two'],
      ['D4', 'Rope'],
    ]) {
      await projects.answer(kit, block, answer);
    }
    await projects.send(kit);
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
    await expect(section.reply).toHaveCount(0);
    await expect.poll(async () => (await projects.work(project, continuation)).state).toBe('running');
    await expect(held.line).not.toHaveAttribute('data-state', 'held');
  });
});

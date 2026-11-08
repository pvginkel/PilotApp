/**
 * A reply's step lines in the Chat tab (decisions 3 and 4), as the session log draws them too: a
 * tool call's line in one colour, a failed one red throughout, with its code — a command without a
 * description, a path, a glob — in the mono face, a search's pattern in its quotes, a command's
 * description standing alone, without the verb, and an agent's description before its type (C4);
 * a call that is no status on its own by the verb it is given, running and done, an MCP call asking
 * its server, a tool with no words of its own used by its name, an agent with no description
 * started (W2).
 * A run of calls is one line whose failures are a count, the one red in it (C3); each text it
 * shows stands for a moment, one that came and went within that moment never shown, and it moves
 * on however fast its calls come, its spinner and its count of failures at once (C1).
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '4f1c8a2e-7b3d-4e9f-a6c5-1d8e2b7f3a90';
const line = (value: object) => JSON.stringify({ ...value, session_id: CONVERSATION });
const text = (id: string, words: string) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] }, parent_tool_use_id: null });
const toolUse = (id: string, name: string, input: object) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'tool_use', id, name, input }] }, parent_tool_use_id: null });
const toolResult = (id: string, content: string, isError = false) =>
  line({
    type: 'user',
    message: { role: 'user', content: [{ tool_use_id: id, type: 'tool_result', content, is_error: isError }] },
    parent_tool_use_id: null,
  });

/** How long a run's line holds a text it shows (`useHeld`'s `HOLD_MS`). */
const HOLD = 200;

const colour = (part: Locator) => part.evaluate((element) => getComputedStyle(element).color);

/** The run's own line, the button over its calls. */
const headOf = (run: Locator) => run.getByRole('button').first();

/** The mouse away from the lines, so that no line takes its hover's colour. */
const away = (page: Page) => page.mouse.move(0, 0);

test.describe('A reply’s step lines', () => {
  test('are one colour, a failed call red throughout and a run’s failures a red count alone; code in the mono face, a description without the verb, an agent’s before its type', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Steps'), members: [me.handle!] });
    await timeline.open(project);
    const { session } = await chats.start(project, 'Where does the cue live?');
    await controller.play(chats.store, session, [
      text('look', 'Looking.'),
      toolUse('read', 'Read', { file_path: '/work/Example/README.md' }),
      toolResult('read', '# Example'),
      toolUse('tests', 'Bash', { command: 'pnpm test', description: 'Run the backend tests' }),
      toolResult('tests', 'Passed.'),
      toolUse('status', 'Bash', { command: 'git status --short\ngit log -1' }),
      toolResult('status', 'M a.ts'),
      toolUse('grep', 'Grep', { pattern: 'cue', path: '/work/Example/src/chat' }),
      toolResult('grep', 'No such directory.', true),
      toolUse('glob', 'Glob', { pattern: 'src/**/*.css' }),
      toolResult('glob', 'src/a.css'),
      text('found', 'It is in the chat.'),
      toolUse('agent', 'Agent', { subagent_type: 'Explore', description: 'Find the cue', prompt: 'Find it.' }),
    ]);

    const run = chat.root.getByTestId('chat.run');
    const head = headOf(run);
    await expect(head).toHaveText('Read a file, ran 2 commands, searched 2 times · 5 steps · 1 failed');
    const failed = run.getByTestId('chat.run.failed');
    await expect(failed).toHaveText('1 failed');
    await expect(chat.root.getByTestId('chat.agent')).toHaveText('Find the cue · Explore agent');

    await head.click();
    const tools = run.getByTestId('chat.tool');
    await expect(tools).toHaveText([
      'Read …/Example/README.md',
      'Run the backend tests',
      'Ran git status --short',
      'Searched for “cue” in …/src/chat — failed',
      'Listed src/**/*.css',
    ]);
    const mono = tools.locator('.mono');
    await expect(mono).toHaveText(['…/Example/README.md', 'git status --short', '…/src/chat', 'src/**/*.css']);
    await expect(mono.first()).toHaveCSS('font-family', /monospace/);
    await expect(tools.nth(1).locator('.mono')).toHaveCount(0);

    await away(page);
    const muted = await colour(tools.first().getByRole('button'));
    const red = await colour(tools.nth(3).getByRole('button'));
    expect(red).not.toBe(muted);
    // The code takes its line's colour, on the red line too.
    expect(await colour(mono.first())).toBe(muted);
    expect(await colour(tools.nth(3).locator('.mono'))).toBe(red);
    // The run's line keeps the usual colour; its count of failures alone is red.
    expect(await colour(head)).toBe(muted);
    expect(await colour(failed)).toBe(red);
  });

  test('words a call that is no status on its own by the verb it is given, running and done: an MCP call asks its server, a tool with no words of its own is used by its name, an agent with no description is started', async ({
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Words'), members: [me.handle!] });
    await timeline.open(project);
    const { session } = await chats.start(project, 'What runs?');
    const tools = chat.root.getByTestId('chat.tool');
    const calls: [string, string, object, string, string][] = [
      ['fleet', 'mcp__kubecoder__start_session', { name: 'example-1' }, 'Asking KubeCoder start session · example-1', 'Asked KubeCoder start session · example-1'],
      ['store', 'mcp__pilot-store__ask_writer', { item: 'invented' }, 'Using ask_writer', 'Used ask_writer'],
      ['skill', 'Skill', { skill: 'survey' }, 'Using Skill', 'Used Skill'],
      // An agent's card heads its steps with its call's words done, its spinner saying that it runs.
      ['agent', 'Agent', { subagent_type: 'Explore', prompt: 'Find it.' }, 'Started the Explore agent', 'Started the Explore agent'],
    ];
    for (const [id, name, input, running, done] of calls) {
      await controller.play(chats.store, session, [text(`before_${id}`, `Next: ${id}.`), toolUse(id, name, input)]);
      await expect(tools.last()).toHaveText(running);
      await controller.play(chats.store, session, [toolResult(id, 'Done.')]);
      await expect(tools.last()).toHaveText(done);
    }
    await expect(tools.first().locator('.mono')).toHaveText('example-1');
    await controller.finish(chats.store, session, 'success', 'Done.');
  });

  test('holds each text of a run’s line for a moment, never showing one that came and went within it, and moves on however fast its calls come; its spinner and its failures at once', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Held'), members: [me.handle!] });
    await page.clock.install();
    await timeline.open(project);
    const { session } = await chats.start(project, 'What is in the folder?');
    await controller.play(chats.store, session, [
      toolUse('read_a', 'Read', { file_path: '/work/Example/a.md' }),
      toolResult('read_a', 'A.'),
      toolUse('list_b', 'Bash', { command: 'ls', description: 'List the files' }),
    ]);
    const run = chat.root.getByTestId('chat.run');
    const head = headOf(run);
    // The run's first text shows as it forms.
    await expect(head).toHaveText('List the files · 2 steps');
    await head.click();
    const tools = run.getByTestId('chat.tool');
    await expect(tools).toHaveCount(2);
    // The page's clock stands still from here: the line's wait ends only as the spec moves it on.
    // eslint-disable-next-line no-restricted-properties -- The page's own clock, read to pause it.
    await page.clock.pauseAt(await page.evaluate(() => Date.now() + 1_000));

    // A failure shows at once, the words held.
    await controller.play(chats.store, session, [toolResult('list_b', 'No such file.', true), toolUse('grep_c', 'Grep', { pattern: 'cue' })]);
    await expect(tools.last()).toHaveText('Searching for “cue”');
    await expect(run.getByTestId('chat.run.failed')).toHaveText('1 failed');
    await expect(head).toHaveText('List the files · 2 steps · 1 failed');
    // The search comes and goes within the wait, and is never shown.
    await controller.play(chats.store, session, [toolResult('grep_c', 'Found.'), toolUse('read_d', 'Read', { file_path: '/work/Example/d.md' })]);
    await expect(tools.last()).toHaveText('Reading …/Example/d.md');
    await expect(head).toHaveText('List the files · 2 steps · 1 failed');
    await page.clock.runFor(HOLD - 1);
    await expect(head).toHaveText('List the files · 2 steps · 1 failed');
    await page.clock.runFor(1);
    await expect(head).toHaveText('Reading …/Example/d.md · 4 steps · 1 failed');

    // A change within the wait does not start it over: the line moves on at its end.
    await controller.play(chats.store, session, [toolResult('read_d', 'D.'), toolUse('glob_e', 'Glob', { pattern: '*.css' })]);
    await expect(tools.last()).toHaveText('Listing *.css');
    await page.clock.runFor(HOLD - 50);
    await controller.play(chats.store, session, [toolResult('glob_e', 'a.css'), toolUse('status_f', 'Bash', { command: 'git status --short' })]);
    await expect(tools.last()).toHaveText('Running git status --short');
    await expect(head).toHaveText('Reading …/Example/d.md · 4 steps · 1 failed');
    await page.clock.runFor(50);
    await expect(head).toHaveText('Running git status --short · 6 steps · 1 failed');

    // The run ends: its spinner goes at once, its words at the wait's end.
    const spinner = head.locator('.animate-spin');
    await expect(spinner).toHaveCount(1);
    await controller.play(chats.store, session, [toolResult('status_f', 'M a.ts'), text('end', 'Two files.')]);
    await expect(chat.texts.last()).toHaveText('Two files.');
    await expect(spinner).toHaveCount(0);
    await expect(head).toHaveText('Running git status --short · 6 steps · 1 failed');
    await page.clock.runFor(HOLD);
    await expect(head).toHaveText('Read 2 files, ran 2 commands, searched 2 times · 6 steps · 1 failed');
  });

  test('moves on from a wait that ends between a frame’s arrival and its drawing', async ({ page, people, projects, controller, timeline, chat, chats }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Held'), members: [me.handle!] });
    // The wait's timer, taken while the page asks for it, runs only right after the next session
    // frame's message has been handled: the frame dispatched, and not yet drawn.
    await page.addInitScript((hold) => {
      const probe = window as Window & { takeHold?: boolean; endHoldAfterFrame?: boolean };
      const setTimer = window.setTimeout.bind(window);
      const clearTimer = window.clearTimeout.bind(window);
      let taken: { id: number; end: () => void } | null = null;
      window.setTimeout = ((end: () => void, ms?: number, ...rest: unknown[]) => {
        if (!probe.takeHold || ms !== hold) return setTimer(end, ms, ...rest);
        taken = { id: setTimer(() => {}, 1e9), end };
        return taken.id;
      }) as typeof window.setTimeout;
      window.clearTimeout = ((id?: number) => {
        if (taken?.id === id) taken = null;
        clearTimer(id);
      }) as typeof window.clearTimeout;
      const onmessage = Object.getOwnPropertyDescriptor(EventSource.prototype, 'onmessage')!;
      Object.defineProperty(EventSource.prototype, 'onmessage', {
        ...onmessage,
        set(this: EventSource, handle: ((event: MessageEvent) => void) | null) {
          onmessage.set!.call(this, (event: MessageEvent) => {
            handle?.call(this, event);
            if (!probe.endHoldAfterFrame || taken === null || (JSON.parse(event.data) as { type: string }).type !== 'session') return;
            const { end } = taken;
            taken = null;
            probe.endHoldAfterFrame = false;
            end();
            document.documentElement.dataset.holdEnded = 'after a frame';
          });
        },
      });
    }, HOLD);
    await timeline.open(project);
    const { session } = await chats.start(project, 'What is in the folder?');
    await controller.play(chats.store, session, [
      toolUse('read_a', 'Read', { file_path: '/work/Example/a.md' }),
      toolResult('read_a', 'A.'),
      toolUse('list_b', 'Bash', { command: 'ls', description: 'List the files' }),
    ]);
    const run = chat.root.getByTestId('chat.run');
    const head = headOf(run);
    await expect(head).toHaveText('List the files · 2 steps');
    await head.click();
    await away(page);
    const tools = run.getByTestId('chat.tool');

    await page.evaluate(() => ((window as Window & { takeHold?: boolean }).takeHold = true));
    await controller.play(chats.store, session, [toolResult('list_b', 'a.md'), toolUse('grep_c', 'Grep', { pattern: 'cue' })]);
    await expect(tools.last()).toHaveText('Searching for “cue”');
    await expect(head).toHaveText('List the files · 2 steps');
    await page.evaluate(() => {
      const probe = window as Window & { takeHold?: boolean; endHoldAfterFrame?: boolean };
      probe.takeHold = false;
      probe.endHoldAfterFrame = true;
    });
    await controller.play(chats.store, session, [toolResult('grep_c', 'Found.')]);
    await expect(page.locator('html')).toHaveAttribute('data-hold-ended', 'after a frame');
    // The wait's end shows the text drawn before that frame, and the next wait the frame's.
    await expect(head).toHaveText('Read a file, ran a command, searched once · 3 steps');
  });
});

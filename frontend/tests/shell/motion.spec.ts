/**
 * Motion under the reduced-motion setting, which Remote Desktop reports (D2): what moves goes
 * instant — the chat's fades, a streamed text's included, the toast's slide-in, the transitions
 * such as the switch's knob and a step line's chevron, the smooth scrolls — and an arriving item's
 * flash holds its ring for its time, with no fade, its end still clearing it; no reply is left
 * hidden. What says that something runs keeps moving: a work item's pulse, the chat's dancing dots,
 * a running call's spinner and the loading bar's stretch. Under no preference everything moves as
 * before. The suite's pages reduce motion (fixtures-infrastructure.ts), so each test here sets the
 * setting itself, both ways.
 */

import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { slowNetwork } from '../support/network';

// Invented lines in `claude`'s shapes (backend/tests/fixtures/raw/), each naming its conversation.
const CONVERSATION = '6d3a9e1f-2c7b-4a85-9f0e-8b4c1d6a2e57';
const line = (value: object) => JSON.stringify({ ...value, session_id: CONVERSATION });
const text = (id: string, words: string) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'text', text: words }] }, parent_tool_use_id: null });
const blockStart = () =>
  line({ type: 'stream_event', event: { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }, parent_tool_use_id: null });
const delta = (words: string) =>
  line({ type: 'stream_event', event: { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: words } }, parent_tool_use_id: null });
const toolUse = (id: string, name: string, input: object) =>
  line({ type: 'assistant', message: { id: `msg_${id}`, content: [{ type: 'tool_use', id, name, input }] }, parent_tool_use_id: null });
const toolResult = (id: string, content: string) =>
  line({ type: 'user', message: { role: 'user', content: [{ tool_use_id: id, type: 'tool_result', content }] }, parent_tool_use_id: null });

const QUESTION = '```question id=Q1\n```\n';
const NOTICE = 'A notice.\n';

const reduce = (page: Page, reduced: boolean) => page.emulateMedia({ reducedMotion: reduced ? 'reduce' : 'no-preference' });

/** Whether anything in the element, its pseudo-elements included, runs an animation, a style's or a script's. */
const moving = (locator: Locator) =>
  locator.evaluate((element) => element.getAnimations({ subtree: true }).some((animation) => animation.playState === 'running'));

/** Each fade's duration and where its opacity stands. */
const fades = (within: Locator) =>
  within
    .locator('.animate-fade-in')
    .evaluateAll((elements) => elements.map((element) => [getComputedStyle(element).animationDuration, getComputedStyle(element).opacity]));

declare global {
  interface Window {
    nextRing?: Promise<string[]>;
  }
}

/**
 * Reads the next flash that starts on the page: its ring at its start and halfway through, the
 * flash held there to read it, then left to run to its end.
 */
async function watchRing(page: Page): Promise<() => Promise<string[]>> {
  await page.evaluate(() => {
    window.nextRing = new Promise<string[]>((resolve) => {
      document.addEventListener('animationstart', function read(event) {
        if (event.animationName !== 'fresh') return;
        document.removeEventListener('animationstart', read);
        const target = event.target as HTMLElement;
        const flash = target.getAnimations().find((animation) => (animation as CSSAnimation).animationName === 'fresh')!;
        flash.pause();
        const at = (time: number) => {
          flash.currentTime = time;
          return getComputedStyle(target).boxShadow;
        };
        const ring = [at(0), at(800)];
        flash.play();
        resolve(ring);
      });
    });
  });
  return () => page.evaluate(() => window.nextRing!);
}

test.describe('Under reduced motion', () => {
  test('a reply in the chat stands at once, its fades and its chevron’s turn instant, while the cue’s dots and a running call’s spinner move; under no preference they fade and turn', async ({
    page,
    people,
    projects,
    controller,
    timeline,
    chat,
    chats,
  }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Motion'), members: [me.handle!] });
    await timeline.open(project);
    const { session } = await chats.start(project, 'Where is the tent?');
    await expect(chat.messageTexts).toHaveText(['Where is the tent?']);
    await controller.play(chats.store, session, [
      text('look', 'Looking.'),
      toolUse('read', 'Read', { file_path: '/work/Example/README.md' }),
    ]);
    const spinner = chat.root.locator('.animate-spin');
    await expect(spinner).toBeVisible();
    await expect(chat.texts).toHaveText(['Looking.']);
    const chevron = chat.root.getByTestId('chat.tool').locator('svg.lucide-chevron-right');

    // The text and the call, and the message where it came by the stream: each on its last frame
    // from the start, shown whole.
    const instant = await fades(chat.root);
    expect(instant.length).toBeGreaterThanOrEqual(2);
    expect(instant).toEqual(instant.map(() => ['0s', '1']));
    await expect(chevron).toHaveCSS('transition-duration', '0s');
    await expect(spinner).toHaveCSS('animation-duration', '1s');
    expect(await moving(spinner)).toBe(true);
    await expect.poll(() => moving(chat.dots)).toBe(true);

    await reduce(page, false);
    // A fade the switch finds under way runs on to its end.
    await expect.poll(() => fades(chat.root)).toEqual(instant.map(() => ['0.2s', '1']));
    await expect(chevron).toHaveCSS('transition-duration', '0.15s');
    expect(await moving(spinner)).toBe(true);
    await expect.poll(() => moving(chat.dots)).toBe(true);

    // A streamed text's latest delta stays fresh until the next comes.
    await controller.play(chats.store, session, [toolResult('read', '# Example'), blockStart(), delta('The tent ')]);
    await expect(chat.phantom).toHaveText('The tent');
    const fresh = chat.phantom.locator('.delta-fresh');
    await expect(fresh).toHaveCSS('animation-duration', '0.3s');
    await reduce(page, true);
    await expect(fresh).toHaveCSS('animation-duration', '0s');
    await expect(fresh).toHaveCSS('opacity', '1');
  });

  test.describe('on the timeline', () => {
    // Short enough that fourteen done lines fill more than the timeline.
    test.use({ viewport: { width: 1280, height: 600 } });

    test('an arrival’s flash holds its ring with no fade, a scroll to an item jumps and the switch’s knob moves at once; under no preference the ring fades, the scroll glides and the knob slides', async ({
      page,
      people,
      projects,
      timeline,
      projectHead,
    }) => {
      const me = await people.signIn();
      const id = await projects.makeWithSession({ name: makeUnique('Motion'), members: [me.handle!] });
      const ask = await projects.place(id, { kind: 'question', title: 'The ask', text: QUESTION });
      for (let index = 0; index < 14; index += 1) {
        const answered = await projects.place(id, { kind: 'question', title: `Answered ${index + 1}`, text: QUESTION });
        await projects.answer(answered, 'Q1', 'Yes');
      }
      await timeline.open(id);
      await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
      const knob = projectHead.autopilot.locator('.knob');

      let ring = await watchRing(page);
      const still = await projects.place(id, { kind: 'notice', title: 'Still', text: NOTICE });
      const [start, middle] = await ring();
      expect(start).toMatch(/ 4px$/);
      expect(middle).toBe(start);
      await expect(timeline.item(still).root).not.toHaveClass(/\bfresh\b/);

      // Read in the click's own task: a jump is there at once, a glide not yet.
      const scrollToAsk = () =>
        timeline.root.evaluate((feed) => {
          const before = feed.scrollTop;
          document.querySelector<HTMLElement>('[data-testid="timeline.open-above"]')!.click();
          return feed.scrollTop - before;
        });
      await expect(timeline.openAbove).toHaveText('1 open above');
      expect(await scrollToAsk()).toBeLessThan(0);
      await expect(timeline.item(ask).root).toBeInViewport();
      await expect(knob).toHaveCSS('transition-duration', '0s');

      await reduce(page, false);
      await timeline.root.evaluate((feed) => feed.scrollTo({ top: feed.scrollHeight }));
      await expect.poll(() => timeline.fromEnd()).toBeLessThan(2);
      ring = await watchRing(page);
      const fading = await projects.place(id, { kind: 'notice', title: 'Fading', text: NOTICE });
      // Faded towards the item's own shadow, a list padded to the ring's length.
      const [from, halfway] = await ring();
      expect(from).toContain(start);
      expect(halfway).not.toContain(start);
      await expect(timeline.item(fading).root).not.toHaveClass(/\bfresh\b/);

      await expect(timeline.openAbove).toHaveText('1 open above');
      expect(await scrollToAsk()).toBe(0);
      await expect(timeline.item(ask).root).toBeInViewport();
      await expect(knob).toHaveCSS('transition-duration', '0.15s');
    });
  });

  test('a work item’s pulse keeps moving, as under no preference', async ({ page, people, projects, controller, timeline }) => {
    const me = await people.signIn();
    const project = await projects.make({ name: makeUnique('Motion'), members: [me.handle!] });
    // The environment the start creates is held `provisioning`.
    await controller.settleCreates(null);
    await timeline.open(project);
    const work = await projects.startWork(project, { title: 'Survey the stylesheets', brief: 'Survey.', cwd: '/work/Example' });
    const pulse = timeline.item(work).work.live.locator('.pulse');
    await expect(pulse).toBeVisible();

    for (const reduced of [true, false]) {
      await reduce(page, reduced);
      await expect(pulse).toHaveCSS('animation-duration', '1.4s');
      expect(await moving(pulse)).toBe(true);
    }
  });

  test('a toast stands at once, while the loading bar’s stretch keeps moving; under no preference the toast slides in', async ({
    page,
    people,
    projects,
    projectList,
    projectHead,
    timeline,
    shell,
  }) => {
    const me = await people.signIn();
    const a = makeUnique('A');
    const aId = await projects.makeWithSession({ name: a, members: [me.handle!] });
    const b = makeUnique('B');
    await projects.makeWithSession({ name: b, members: [me.handle!] });
    await timeline.open(aId);

    const toast = async (message: string) => {
      await page.evaluate((words) => {
        window.dispatchEvent(new CustomEvent('app:testing:show-exception', { detail: { message: words, error: new Error(words) } }));
      }, message);
      const item = page.getByTestId('app-shell.toast.item').filter({ hasText: message });
      await expect(item).toBeVisible();
      return item;
    };
    const still = await toast('Standing');
    await expect(still).toHaveCSS('animation-duration', '0s');
    await expect(still).toHaveCSS('transition-duration', '0s');
    await reduce(page, false);
    const sliding = await toast('Sliding');
    await expect(sliding).toHaveCSS('animation-duration', '0.15s');
    await expect(sliding).toHaveCSS('transition-duration', '0.15s');

    await reduce(page, true);
    const restore = await slowNetwork(page, 800);
    await projectList.tab(b).click();
    await expect(shell.loading).toBeVisible();
    expect(await shell.loading.evaluate((bar) => getComputedStyle(bar, '::before').animationDuration)).toBe('1.2s');
    expect(await moving(shell.loading)).toBe(true);
    await expect(projectHead.name).toHaveText(b);
    await restore();
  });
});

/**
 * The screens kept live (F80.2): the server's `project_changed` reads again what the screens show
 * of the project it names — its timeline, its head and the tabs' badges — leaving a read under way
 * to land first, and a stream that comes back up reads them all again, covering whatever it missed
 * while it was down. A timeline no screen shows is read again once its project is shown, a work
 * item's move written into it after the change notwithstanding. The page whose write the event is
 * reads nothing on it: its write reads every query again, once.
 */

import type { Request } from '@playwright/test';
import type { TestEvent } from '@/lib/test/test-events';
import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { createDeploymentSseHelper } from '../support/helpers/deployment-sse';
import { PageFetches, slowNetwork } from '../support/network';
import { ProjectHeadPage } from '../support/page-objects/project-head-page';
import type { TimelinePage } from '../support/page-objects/timeline-page';
import { projectAddress } from '../support/projects';

const QUESTION = '```question id=Q1\n```\n';
const DECISION = '```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';

const WRITES: { what: string; kind: 'decision' | 'notice'; text: string; act: (item: ReturnType<TimelinePage['item']>) => Promise<void> }[] = [
  { what: 'An option picked', kind: 'decision', text: DECISION, act: (item) => item.block.option('Tunnel').click() },
  { what: 'A notice marked Read', kind: 'notice', text: 'A storm comes.\n', act: (item) => item.read.click() },
];

test.describe('Live updates', () => {
  test('an answer and an item from elsewhere reach the open timeline and the tab’s badge without a reload', async ({
    people,
    projects,
    projectList,
    timeline,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Live');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    const ask = await projects.place(id, { kind: 'question', title: 'Which lake?', text: QUESTION });
    await timeline.open(id);
    await deploymentSse.ensureConnected();
    await expect(projectList.badge(name)).toHaveText('1');

    await projects.answer(ask, 'Q1', 'North');
    await expect(timeline.item(ask).said).toHaveText('North');
    await expect(projectList.badge(name)).toHaveCount(0);

    const storm = await projects.place(id, { kind: 'notice', title: 'Storm', text: '---\nurgent: true\n---\n\nA storm comes.\n' });
    await expect(timeline.item(storm).root).toHaveClass(/\bfresh\b/);
    await expect(timeline.banner(storm)).toBeVisible();
    await expect(projectList.badge(name)).toHaveText('1');
    await expect(projectList.badge(name)).toHaveAttribute('data-urgent', 'true');
  });

  test('a change made while the timeline is being read leaves that read to land, and the timeline is read again after it', async ({
    page,
    people,
    projects,
    timeline,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Under way'), members: [me.handle!] });
    const isRead = (request: Request) => new URL(request.url()).pathname === `/api/projects/${id}/timeline`;
    const reads = new Set<Request>();
    let most = 0;
    page.on('request', (request) => {
      if (!isRead(request)) return;
      reads.add(request);
      most = Math.max(most, reads.size);
    });
    page.on('response', (response) => reads.delete(response.request()));
    await timeline.open(id);
    await deploymentSse.ensureConnected();

    // Each read the page sends takes a second, and the second change's event comes while the read
    // the first change's sent is under way.
    const restore = await slowNetwork(page, 1_000);
    most = reads.size;
    const read = page.waitForRequest(isRead);
    const one = await projects.place(id, { kind: 'notice', title: 'One', text: 'One.\n' });
    await read;
    const two = await projects.place(id, { kind: 'notice', title: 'Two', text: 'Two.\n' });
    await expect(timeline.item(one).root).toBeVisible();
    await expect(timeline.item(two).root).toBeVisible();
    expect(most).toBe(1);
    await restore();
  });

  for (const write of WRITES) {
    test(`${write.what} reads each query the page shows once, the timeline built once`, async ({
      page,
      people,
      projects,
      timeline,
      deploymentSse,
      testEvents,
    }) => {
      const me = await people.signIn();
      const id = await projects.makeWithSession({ name: makeUnique('Once'), members: [me.handle!] });
      const placed = await projects.place(id, { kind: write.kind, title: 'Which tent?', text: write.text });
      await timeline.open(id);
      await deploymentSse.ensureConnected();
      const item = timeline.item(placed);
      await expect(item.root).toBeVisible();

      // Each query's reads, by its address, from the click on.
      const reads = new Map<string, number>();
      page.on('request', (request) => {
        const url = new URL(request.url());
        if (request.resourceType() !== 'fetch' || request.method() !== 'GET' || !url.pathname.startsWith('/api/')) return;
        reads.set(url.pathname + url.search, (reads.get(url.pathname + url.search) ?? 0) + 1);
      });
      const fetches = new PageFetches(page);
      await write.act(item);

      await expect(item.root).toHaveAttribute('data-state', 'done');
      await testEvents.waitForEvent(
        (event) => event.kind === 'sse' && event.streamId === 'project_changed' && (event.data as { project_id: string }).project_id === id,
      );
      // The page's own handling of the event has run, and every read it started, and any read owed
      // over one under way, has landed.
      await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 0)));
      await fetches.landed();
      await fetches.landed();
      expect(reads.get(`/api/projects/${id}/timeline`)).toBe(1);
      expect([...reads].filter(([, count]) => count > 1)).toEqual([]);
    });
  }

  test('a timeline left while an item of it is done is read again on the switch back, a work item’s move written into it after the change notwithstanding', async ({
    page,
    people,
    projects,
    projectList,
    timeline,
    deploymentSse,
    testEvents,
  }) => {
    const me = await people.signIn();
    const name = makeUnique('Left');
    const other = makeUnique('Elsewhere');
    const id = await projects.makeWithSession({ name, members: [me.handle!] });
    const otherId = await projects.make({ name: other, members: [me.handle!] });
    const route = await projects.place(id, { kind: 'document', title: 'The route', text: 'We leave on Friday.\n' });
    const work = await projects.startWork(id, { title: 'Surveying the stylesheets', brief: 'Survey the stylesheets.', cwd: '/work/Example' });
    await expect.poll(async () => (await projects.work(id, work)).state).toBe('running');
    await timeline.open(id);
    await deploymentSse.ensureConnected();
    await expect(timeline.item(work).work.running).toBeVisible();
    await expect(timeline.item(route).root).not.toHaveAttribute('data-state', 'done');

    // The project's timeline stays in the cache, no screen showing it.
    await projectList.tab(other).click();
    await expect(page).toHaveURL(projectAddress(otherId));
    await testEvents.clearEvents();
    const heard = (stream: string, item?: string) => (event: TestEvent) => {
      const data = event.kind === 'sse' && event.streamId === stream ? (event.data as { project_id: string; item_id?: string }) : undefined;
      return data?.project_id === id && (item === undefined || data.item_id === item);
    };

    // The document is done: the project's change marks its timeline to be read again ...
    await projects.doneByPilot(route);
    await testEvents.waitForEvent(heard('project_changed'));
    await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 0)));
    // ... and the work item's move, heard after it, is written into the timeline as read.
    await projects.setProgress(work, [{ code: 'a', label: 'Step a', state: 'active' }]);
    await testEvents.waitForEvent(heard('work_moved', work));

    await projectList.tab(name).click();
    await expect(page).toHaveURL(projectAddress(id));
    await expect(timeline.item(route).root).toHaveAttribute('data-state', 'done');
  });

  test('a second tab follows the head the first one changes', async ({ context, people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Tabs'), members: [me.handle!] });
    const other = await context.newPage();
    const otherHead = new ProjectHeadPage(other);
    await other.goto(projectAddress(id));
    await expect(otherHead.autopilot).toHaveAttribute('aria-checked', 'false');
    await createDeploymentSseHelper(other).ensureConnected();

    await projectHead.open(id);
    await projectHead.autopilot.click();
    await expect(projectHead.autopilot).toHaveAttribute('aria-checked', 'true');
    await expect(otherHead.autopilot).toHaveAttribute('aria-checked', 'true');
  });

  test('a stream that comes back up reads again what it missed while it was down', async ({
    page,
    backendUrl,
    auth,
    people,
    projects,
    timeline,
    deploymentSse,
    toastHelper,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Down'), members: [me.handle!] });
    await timeline.open(id);
    await deploymentSse.ensureConnected();

    // The stream goes down and stays down: its next connect is refused, and the session check
    // that would open it again fails.
    const refusal = await page.request.post(`${backendUrl}/api/testing/sse/force-callback-error?status=403`);
    expect(refusal.status()).toBe(204);
    await auth.forceError(500);
    await page.evaluate(() => window.__sseForceReconnect!());
    await toastHelper.expectErrorToast(/refresh the page/i);
    expect((await deploymentSse.getStatus()).isConnected).toBe(false);

    const missed = await projects.place(id, { kind: 'notice', title: 'Missed', text: 'One.\n' });
    await deploymentSse.connect();
    await expect(timeline.item(missed).root).toBeVisible();
  });
});

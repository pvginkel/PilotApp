/**
 * The screens kept live (F80.2): the server's `project_changed` reads again what the screens show
 * of the project it names — its timeline, its head and the tabs' badges — and a stream that comes
 * back up reads them all again, covering whatever it missed while it was down.
 */

import { test, expect } from '../support/fixtures';
import { makeUnique } from '../support/helpers';
import { createDeploymentSseHelper } from '../support/helpers/deployment-sse';
import { ProjectHeadPage } from '../support/page-objects/project-head-page';

const QUESTION = '```question id=Q1\n```\n';

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

  test('a second tab follows the head the first one changes', async ({ context, people, projects, projectHead }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Tabs'), members: [me.handle!] });
    const other = await context.newPage();
    const otherHead = new ProjectHeadPage(other);
    await other.goto(`/projects/${id}`);
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

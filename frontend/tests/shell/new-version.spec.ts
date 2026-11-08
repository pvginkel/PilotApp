/**
 * A new version deployed: Pilot reloads itself (`src/lib/config/new-version.ts`), with no banner,
 * once the reload takes nothing being typed in: no field holds words it would put out of sight, no
 * write is on its way, and no field has the focus but as the tab comes back into view.
 */

import type { Page } from '@playwright/test';
import { test, expect } from '../support/fixtures';
import { makeUnique, waitTestEvent } from '../support/helpers';
import type { DeploymentSseHelper } from '../support/helpers/deployment-sse';
import { slowNetwork } from '../support/network';
import type { UiStateTestEvent } from '@/lib/test/test-events';

const DECISION = 'Which tent for the trip?\n\n```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n';

type Hold = 'words' | 'write' | 'focus';

/**
 * The page's stream connected, its first version taken as the one it runs; the returned call
 * deploys a newer one.
 */
async function deployed(page: Page, backendUrl: string, deploymentSse: DeploymentSseHelper): Promise<() => Promise<void>> {
  const { requestId } = await deploymentSse.ensureConnected();
  const send = async (version: string) => {
    const response = await page.request.post(`${backendUrl}/api/testing/deployments/version`, {
      data: { request_id: requestId, version },
    });
    expect(response.ok()).toBe(true);
  };
  const running = makeUnique('running');
  await send(running);
  await deploymentSse.waitForCurrentVersion(running);
  return () => send(makeUnique('newer'));
}

/** The reload held, for the reason given. */
function held(page: Page, hold: Hold): Promise<UiStateTestEvent> {
  return waitTestEvent<UiStateTestEvent>(page, 'ui_state', (event) => event.scope === 'deployment.reload' && event.metadata?.held === hold);
}

test.describe('A new version', () => {
  test('reloads the page by itself, with no banner', async ({ page, backendUrl, people, shell, deploymentSse }) => {
    await people.signIn();
    await shell.open();
    const newer = await deployed(page, backendUrl, deploymentSse);
    await page.evaluate(() => Object.assign(window, { beforeTheReload: true }));

    const reloaded = page.waitForEvent('load');
    await newer();
    await reloaded;
    expect(await page.evaluate(() => 'beforeTheReload' in window)).toBe(false);
    await deploymentSse.ensureConnected();
    await expect(shell.app).toBeVisible();
    await expect(page.getByTestId('deployment.banner')).toHaveCount(0);
  });

  test('waits while a console holds words, its field without the focus, then while their answer is on its way, and reloads once it is saved', async ({
    page,
    backendUrl,
    people,
    projects,
    timeline,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const id = await projects.makeWithSession({ name: makeUnique('Half written'), members: [me.handle!] });
    const decision = await projects.place(id, { kind: 'decision', title: 'Which tent?', text: DECISION });
    await timeline.open(id);
    const { block } = timeline.item(decision);
    const newer = await deployed(page, backendUrl, deploymentSse);

    await block.other.click();
    await block.field.fill('Neither: the van');
    // To the console's Send, a button.
    await block.field.press('Tab');
    await expect(block.send).toBeFocused();
    const holding = held(page, 'words');
    await newer();
    await holding;
    await expect(block.field).toHaveValue('Neither: the van');

    // The console closes on Send, before its answer is saved.
    const restore = await slowNetwork(page, 3_000);
    const writing = held(page, 'write');
    await block.send.click();
    await expect(block.console).toHaveCount(0);
    await writing;
    const reloaded = page.waitForEvent('load');
    await restore();
    await reloaded;
    expect((await projects.block(id, decision)).answer).toBe('Neither: the van');
  });

  test('waits while a field has the focus, its words kept in the browser, and reloads once it loses it', async ({
    page,
    backendUrl,
    people,
    projects,
    timeline,
    chat,
    deploymentSse,
  }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Focused'), members: [me.handle!] });
    await timeline.open(id);
    const newer = await deployed(page, backendUrl, deploymentSse);

    await chat.field.fill('Shall we go after all?');
    const holding = held(page, 'focus');
    await newer();
    await holding;
    await expect(chat.field).toBeFocused();

    const reloaded = page.waitForEvent('load');
    await chat.field.press('Tab');
    await reloaded;
    await expect(chat.field).toHaveValue('Shall we go after all?');
  });

  test('reloads as the tab comes back into view, the focus in a field aside', async ({ page, backendUrl, people, projects, timeline, chat, deploymentSse }) => {
    const me = await people.signIn();
    const id = await projects.make({ name: makeUnique('Back in view'), members: [me.handle!] });
    await timeline.open(id);
    const newer = await deployed(page, backendUrl, deploymentSse);

    await chat.field.focus();
    const holding = held(page, 'focus');
    await newer();
    await holding;

    const view = (state: DocumentVisibilityState) =>
      page.evaluate((state) => {
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
        Object.defineProperty(document, 'hidden', { configurable: true, get: () => state === 'hidden' });
        // After the evaluate has answered: the reload it sets off ends the page's context.
        setTimeout(() => document.dispatchEvent(new Event('visibilitychange')));
      }, state);
    await view('hidden');
    await expect(chat.field).toBeFocused();
    const reloaded = page.waitForEvent('load');
    await view('visible');
    await reloaded;
  });
});

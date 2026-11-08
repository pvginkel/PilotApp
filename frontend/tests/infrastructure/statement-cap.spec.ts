/**
 * The statement cap (backend/app/utils/statement_cap.py): the worker's backend keeps each statement
 * it sends over 2,000 characters, measured before an IN list's ids are filled in, and the
 * `statementCap` fixture fails the test on any once it is done. No route of the app's sends one, so
 * the spec has the backend send one through POST /api/testing/statement-cap/send and takes it
 * itself.
 */

import type { APIRequestContext } from '@playwright/test';
import { expect, test } from '../support/fixtures';

const CAP = 2_000;

async function send(request: APIRequestContext, length: number, ids: number): Promise<void> {
  const response = await request.post('/api/testing/statement-cap/send', { data: { length, ids } });
  expect(response.status(), await response.text()).toBe(204);
}

async function take(request: APIRequestContext): Promise<string[]> {
  const response = await request.post('/api/testing/statement-cap/take');
  expect(response.ok(), await response.text()).toBe(true);
  return ((await response.json()) as { statements: string[] }).statements;
}

test.describe('The statement cap', () => {
  let request: APIRequestContext;

  test.beforeEach(async ({ playwright, backendUrl }) => {
    request = await playwright.request.newContext({ baseURL: backendUrl });
  });

  test.afterEach(async () => {
    await request.dispose();
  });

  test('keeps a statement over 2,000 characters, told by its length, where it was sent and its text', async () => {
    await send(request, CAP + 1, 1);

    expect(await take(request)).toEqual([
      expect.stringMatching(
        /^A statement of 2,001 characters, over its bound of 2,000, sent at:\n[\s\S]*app\/api\/testing_statement_cap\.py:\d+ in send_statement\nSELECT 1 WHERE 1 IN \(__\[POSTCOMPILE_ids\]\) -- -+$/
      ),
    ]);
  });

  test('counts none of an IN list’s ids', async () => {
    await send(request, CAP, 1_000);

    expect(await take(request)).toEqual([]);
  });
});

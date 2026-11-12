/**
 * The fixtures that fail a spec on its backend's faults (`tests/support/fixtures.ts`): `statementCap`
 * fails a spec that leaves its backend's statement over 2,000 characters untaken, and `poolGuard` one
 * that leaves its backend's nesting, a second connection of the pool checked out while it held one.
 * Each spec has the backend make its fault through a testing route, POST
 * /api/testing/statement-cap/send, as statement-cap.spec.ts does, or POST /api/testing/pool-guard/nest,
 * and leaves it to its fixture, under `test.fail()`: it passes only as the fixture fails it. One fault
 * to a spec, so that the other fixture's failure cannot pass it.
 */

import type { APIRequestContext } from '@playwright/test';
import { expect, test } from '../support/fixtures';

test.describe('The fixtures on the backend’s faults', () => {
  let request: APIRequestContext;

  test.beforeEach(async ({ playwright, backendUrl }) => {
    request = await playwright.request.newContext({ baseURL: backendUrl });
  });

  test.afterEach(async () => {
    await request.dispose();
  });

  test('fail a spec that leaves its backend’s statement over 2,000 characters', async () => {
    test.fail();
    const response = await request.post('/api/testing/statement-cap/send', { data: { length: 2_001, ids: 1 } });
    expect(response.status(), await response.text()).toBe(204);
  });

  test('fail a spec that leaves its backend’s nesting', async () => {
    test.fail();
    const response = await request.post('/api/testing/pool-guard/nest');
    expect(response.status(), await response.text()).toBe(204);
  });
});

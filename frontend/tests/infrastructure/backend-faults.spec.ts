/**
 * The fixtures that fail a spec on its backend's faults (`tests/support/fixtures.ts`): `statementCap`
 * fails a spec that leaves its backend's statement over 2,000 characters untaken. The spec has the
 * backend send one through POST /api/testing/statement-cap/send, as statement-cap.spec.ts does, and
 * leaves it to the fixture, under `test.fail()`: it passes only as the fixture fails it.
 */

import { expect, test } from '../support/fixtures';

test.describe('The fixtures on the backend’s faults', () => {
  test('fail a spec that leaves its backend’s statement over 2,000 characters', async ({ playwright, backendUrl }) => {
    test.fail();
    const request = await playwright.request.newContext({ baseURL: backendUrl });
    try {
      const response = await request.post('/api/testing/statement-cap/send', { data: { length: 2_001, ids: 1 } });
      expect(response.status(), await response.text()).toBe(204);
    } finally {
      await request.dispose();
    }
  });
});

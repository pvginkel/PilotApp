/**
 * Domain-specific test fixtures.
 * App-owned — extends infrastructure fixtures with domain page objects.
 *
 * Example:
 *   import { test as infrastructureTest } from './fixtures-infrastructure';
 *
 *   export const test = infrastructureTest.extend<{ myPage: MyPageObject }>({
 *     myPage: async ({ page }, use) => {
 *       await use(new MyPageObject(page));
 *     },
 *   });
 *
 *   export { expect } from '@playwright/test';
 *
 * A fixture's `use` callback reads to eslint as React's `use` hook, so
 * react-hooks/rules-of-hooks reports it: once the file defines a fixture, put
 * an `eslint-disable react-hooks/rules-of-hooks` block comment above the code.
 * Until then the directive would disable nothing, and eslint warns about it.
 */

export { infrastructureFixtures as test } from './fixtures-infrastructure';
export type { InfrastructureFixtures } from './fixtures-infrastructure';
export { expect } from '@playwright/test';

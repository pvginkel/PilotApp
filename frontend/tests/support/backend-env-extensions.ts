/**
 * App-owned environment extensions — merged over the environment of each backend the Playwright
 * workers start (tests/support/process/servers.ts), after the template's own.
 * Modify this file to give the suite's backends app-specific settings.
 * This file is never overwritten by template updates.
 */

import { generateKeyPairSync } from 'node:crypto';

// Invented: the bearer the backend's client sends its own fake, which checks it.
export const FAKE_CONTROLLER_TOKEN = 'playwright-fake-controller';

// Invented: the store's environment, where every chat's session runs, in the backend's fake
// (tests/support/chats.ts puts it there).
export const STORE_ENVIRONMENT = 'playwright-store';

// More work items than a worker's specs start.
const UNBOUNDED_WORK = 10_000;

// Longer than a worker's specs run: the batcher places no wait's run, and a spec places it
// (tests/support/waits.ts).
const NO_BATCH_SECONDS = 86_400;

/** The settings of the backend serving at `backendUrl`. */
export function loadAppBackendEnv(backendUrl: string): NodeJS.ProcessEnv {
  return {
    // The backend's controller is its own fake, mounted under /api/testing/controller in testing
    // mode (backend/app/api/testing_controller.py); tests/support/controller.ts drives it.
    CONTROLLER_URL: `${backendUrl}/api/testing/controller`,
    CONTROLLER_TOKEN: FAKE_CONTROLLER_TOKEN,
    // A worker's specs share its backend and leave work items running, each spec in projects of
    // its own: the slot across every project never closes, and one project's closes at 3.
    WORK_PARALLELISM_MAX: String(UNBOUNDED_WORK),
    PROJECT_PARALLELISM_MAX: '3',
    STORE_ENVIRONMENT_ID: STORE_ENVIRONMENT,
    WAIT_QUIET_WINDOW_SECONDS: String(NO_BATCH_SECONDS),
    // The backend's VAPID key, minted for it, as no key is committed. It pushes to subscriptions its
    // own fake push service issues, mounted under /api/testing/push-service in testing mode
    // (backend/app/api/testing_push_service.py); tests/support/browser-push.ts takes them.
    VAPID_PRIVATE_KEY: generateKeyPairSync('ec', {
      namedCurve: 'P-256',
      publicKeyEncoding: { type: 'spki', format: 'pem' },
      privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
    }).privateKey,
    // The five-hour halt stops every running work item (tests/work/hard-stop.spec.ts); the week's
    // keeps its default, the cooperative stop.
    FIVE_HOUR_HALT: 'hard_stop',
    // The pool guard on the backend's pool (backend/app/utils/pool_guard.py): fixtures.ts takes its
    // nestings after each test, under /api/testing/pool-guard, and fails the test on any.
    POOL_GUARD: 'true',
    // The statement cap on the backend's engine (backend/app/utils/statement_cap.py): fixtures.ts
    // takes the statements over it after each test, under /api/testing/statement-cap, and fails the
    // test on any.
    STATEMENT_CAP: 'true',
  };
}

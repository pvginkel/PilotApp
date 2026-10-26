/**
 * App-owned environment extensions — merged over the environment of each backend the Playwright
 * workers start (tests/support/process/servers.ts), after the template's own.
 * Modify this file to give the suite's backends app-specific settings.
 * This file is never overwritten by template updates.
 */

// Invented: the bearer the backend's client sends its own fake, which checks it.
export const FAKE_CONTROLLER_TOKEN = 'playwright-fake-controller';

// Invented: the store's environment, where every chat's session runs, in the backend's fake
// (tests/support/chats.ts puts it there).
export const STORE_ENVIRONMENT = 'playwright-store';

// More work items than a worker's specs start.
const UNBOUNDED_WORK = 10_000;

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
  };
}

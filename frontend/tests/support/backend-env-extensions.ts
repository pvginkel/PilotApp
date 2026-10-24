/**
 * App-owned environment extensions — merged over the environment of each backend the Playwright
 * workers start (tests/support/process/servers.ts), after the template's own.
 * Modify this file to give the suite's backends app-specific settings.
 * This file is never overwritten by template updates.
 */

// Invented: the bearer the backend's client sends its own fake, which checks it.
const FAKE_CONTROLLER_TOKEN = 'playwright-fake-controller';

/** The settings of the backend serving at `backendUrl`. */
export function loadAppBackendEnv(backendUrl: string): NodeJS.ProcessEnv {
  return {
    // The backend's controller is its own fake, mounted under /api/testing/controller in testing
    // mode (backend/app/api/testing_controller.py); tests/support/controller.ts drives it.
    CONTROLLER_URL: `${backendUrl}/api/testing/controller`,
    CONTROLLER_TOKEN: FAKE_CONTROLLER_TOKEN,
  };
}

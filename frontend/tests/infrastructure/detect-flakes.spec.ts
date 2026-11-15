/**
 * The detect-flakes mode (tests/support/detect-flakes.ts): in a session's run, a failing test is
 * rerun twice, a test that passed only on a rerun is named flaky, apart from those that failed every
 * attempt, and keeps the run red, and past the cap a failing test is not rerun. Pinned on nested
 * Playwright runs of invented tests, which take the mode's own settings, on a cap of 2: no browser,
 * no backend and no test suite lock, so each takes seconds.
 */

import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import RerunCapReporter, { detectFlakes, RERUN_CAP, RERUNS } from '../support/detect-flakes';

const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const PLAYWRIGHT = join(FRONTEND, 'node_modules/@playwright/test');
const MODULE = join(FRONTEND, 'tests/support/detect-flakes.ts');

// Outside the frontend, whose node_modules Playwright never transforms: every import absolute.
const CONFIG = `
import { defineConfig } from ${JSON.stringify(join(PLAYWRIGHT, 'index.mjs'))};
import { detectFlakes } from ${JSON.stringify(MODULE)};

const flakes = detectFlakes(true, 2);

export default defineConfig({
  testDir: '.',
  workers: 1,
  fullyParallel: false,
  retries: flakes.retries,
  failOnFlakyTests: flakes.failOnFlakyTests,
  reporter: [...flakes.reporters, ['list'], ['json', { outputFile: 'results.json' }]],
});
`;

// In this order on the one worker: each failure's rerun is queued after the tests not yet run, so
// the third test's first attempt is the run's third failure, past the cap of 2.
const CASES = `
import { expect, test } from ${JSON.stringify(join(PLAYWRIGHT, 'index.mjs'))};

test('passes on a rerun', ({}, testInfo) => {
  expect(testInfo.retry).toBeGreaterThan(0);
});

test('fails every attempt', () => {
  expect('every attempt').toBe('none');
});

test('fails past the cap', () => {
  expect('past the cap').toBe('none');
});
`;

interface JsonReport {
  suites: { specs: { title: string; tests: { results: { status: string }[] }[] }[] }[];
}

interface NestedRun {
  status: number | null;
  output: string;
  /** Each test's attempts, by its title. */
  attempts: Record<string, string[]>;
}

test.describe('The detect-flakes mode', () => {
  let dir: string;

  test.beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'detect-flakes-'));
    writeFileSync(join(dir, 'package.json'), '{ "type": "module" }\n');
    writeFileSync(join(dir, 'playwright.config.ts'), CONFIG);
    writeFileSync(join(dir, 'cases.spec.ts'), CASES);
  });

  test.afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  function run(...args: string[]): NestedRun {
    const child = spawnSync(process.execPath, [join(PLAYWRIGHT, 'cli.js'), 'test', ...args], {
      cwd: dir,
      // None of this run's: neither its worker's variables nor a CI's.
      env: { PATH: process.env.PATH, HOME: process.env.HOME, FORCE_COLOR: '0' },
      encoding: 'utf8',
      timeout: 60_000,
    });
    const report = JSON.parse(readFileSync(join(dir, 'results.json'), 'utf8')) as JsonReport;
    const attempts: Record<string, string[]> = {};
    for (const spec of report.suites.flatMap(suite => suite.specs)) {
      attempts[spec.title] = spec.tests.flatMap(t => t.results.map(result => result.status));
    }
    return { status: child.status, output: `${child.stdout}${child.stderr}`, attempts };
  }

  test('names a test that passed only on a rerun flaky, and keeps the run red', () => {
    test.setTimeout(90_000);

    const nested = run('--grep', 'passes on a rerun');

    expect(nested.attempts).toEqual({ 'passes on a rerun': ['failed', 'passed'] });
    expect(nested.status, nested.output).toBe(1);
    expect(nested.output).toMatch(/\n {2}1 flaky\n.*passes on a rerun/);
    expect(nested.output).toContain(
      '🔁 The run is red: 1 test passed only on a rerun, named flaky above. A test named failed failed every attempt.'
    );
  });

  test('reruns a failing test twice, and none past the cap, saying the cap was reached', () => {
    test.setTimeout(90_000);

    const nested = run();

    expect(nested.attempts).toEqual({
      'passes on a rerun': ['failed', 'passed'],
      'fails every attempt': ['failed', 'failed', 'failed'],
      'fails past the cap': ['failed'],
    });
    expect(nested.status, nested.output).toBe(1);
    expect(nested.output).toMatch(/\n {2}2 failed\n.*fails every attempt.*\n.*fails past the cap.*\n {2}1 flaky\n/);
    expect(nested.output).toContain(
      '🔁 The cap of 2 failed tests a run was reached: past it, 1 test failed once and was not rerun:\n' +
        '    cases.spec.ts:12:1 › fails past the cap'
    );
  });

  test('is on in a session’s run alone, CI’s keeping the template’s settings', async () => {
    expect(detectFlakes(false)).toEqual({ retries: 0, failOnFlakyTests: false, reporters: [] });
    expect(detectFlakes(true)).toEqual({
      retries: RERUNS,
      failOnFlakyTests: true,
      reporters: [[MODULE, { cap: RERUN_CAP }]],
    });
    expect(RERUNS).toBe(2);
    // The operator, 2026-11-15: "Cap at 10".
    expect(RERUN_CAP).toBe(10);
    // Playwright loads a reporter by its module's path and takes its default export.
    const loaded = (await import(MODULE)) as { default: unknown };
    expect(loaded.default).toBe(RerunCapReporter);
  });
});

/**
 * The detect-flakes mode (F122.7): in every run a session makes, a failing test is rerun twice, the
 * run's output names each test that passed only on a rerun apart from the tests that failed every
 * attempt, and the run stays red. A session's run is one that takes the test suite lock
 * (test-suite-lock.ts): inside KubeCoder, beside the spec repo, so never CI's. CI's run keeps the
 * template's settings: run-suite passes --retries=2, and a test that passes on a retry passes.
 *
 * Playwright names a flaky test under a heading of its own, apart from the failed, and
 * `failOnFlakyTests` keeps the run red. Past the cap, a failing test is not rerun: this module's
 * reporter takes the test's retries away as its first attempt ends, before Playwright's dispatcher
 * reads them to queue the rerun, so that no worker boots its services for an attempt that would not
 * run. A fixture cannot do it: a rerun it skips makes the test flaky, the skip becoming the test's
 * expected status, and one it fails boots the worker's services first.
 * tests/infrastructure/detect-flakes.spec.ts pins both on a nested run.
 */

import { relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { ReporterDescription } from '@playwright/test';
import type { FullConfig, Reporter, Suite, TestCase, TestResult } from '@playwright/test/reporter';
import { testSuiteLockFile } from './test-suite-lock';

/** How many times a failing test is rerun. */
export const RERUNS = 2;

/**
 * How many failing tests a run reruns; past them, a failing test is not rerun. The operator,
 * 2026-11-15: "Cap at 10" (PilotAppSpecs, tools/cost-dashboard/asks/t15-rerun-cap.md).
 */
export const RERUN_CAP = 10;

/** The settings of the mode that the Playwright config takes. */
interface DetectFlakes {
  retries: number;
  failOnFlakyTests: boolean;
  /** Before the list reporter, so that it reads a test's retries once this reporter has set them. */
  reporters: ReporterDescription[];
}

/** The mode's settings: on in a session's run, else the template's. */
export function detectFlakes(on: boolean = testSuiteLockFile() !== null, cap: number = RERUN_CAP): DetectFlakes {
  if (!on) {
    return { retries: 0, failOnFlakyTests: false, reporters: [] };
  }
  return { retries: RERUNS, failOnFlakyTests: true, reporters: [[fileURLToPath(import.meta.url), { cap }]] };
}

/** Takes the retries of each failing test past the cap away, and says what the mode found. */
export default class RerunCapReporter implements Reporter {
  private readonly cap: number;
  private rootDir = '';
  private suite: Suite | undefined;
  private failed = 0;
  private readonly pastCap: TestCase[] = [];

  constructor(options: { cap?: number } = {}) {
    this.cap = options.cap ?? RERUN_CAP;
  }

  onBegin(config: FullConfig, suite: Suite): void {
    this.rootDir = config.rootDir;
    this.suite = suite;
  }

  onTestEnd(test: TestCase, result: TestResult): void {
    // A failed first attempt of a test that would be rerun: the first `cap` are, the rest not.
    const failed = !['skipped', 'interrupted', test.expectedStatus].includes(result.status);
    if (!failed || result.retry > 0 || test.retries === 0) {
      return;
    }
    this.failed += 1;
    if (this.failed > this.cap) {
      test.retries = 0;
      this.pastCap.push(test);
    }
  }

  // After every reporter's onEnd, so that the lines follow the list reporter's summary.
  async onExit(): Promise<void> {
    const flaky = this.suite?.allTests().filter(test => test.outcome() === 'flaky') ?? [];
    if (flaky.length > 0) {
      console.log(
        `\n  🔁 The run is red: ${tests(flaky.length)} passed only on a rerun, named flaky above. ` +
          'A test named failed failed every attempt.'
      );
    }
    if (this.pastCap.length > 0) {
      const one = this.pastCap.length === 1;
      console.log(
        `\n  🔁 The cap of ${this.cap} failed tests a run was reached: past it, ` +
          `${tests(this.pastCap.length)} failed once and ${one ? 'was' : 'were'} not rerun:`
      );
      for (const test of this.pastCap) {
        console.log(`    ${this.describe(test)}`);
      }
    }
  }

  printsToStdio(): boolean {
    return false;
  }

  private describe(test: TestCase): string {
    const { file, line, column } = test.location;
    return [`${relative(this.rootDir, file)}:${line}:${column}`, ...test.titlePath().slice(3)].join(' › ');
  }
}

function tests(count: number): string {
  return count === 1 ? '1 test' : `${count} tests`;
}

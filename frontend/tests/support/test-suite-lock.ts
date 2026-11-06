/**
 * The test suite lock: one Playwright run at a time across the project's KubeCoder environments.
 * Every environment runs on one 8-core node, and two suites at four workers each saturate it:
 * their tests fail on timeouts and every session on the node lags (P-221).
 *
 * The lock is a flock on a file in the spec repo, whose checkout every environment of the project
 * mounts from one directory on that node: one kernel, so the flock reaches across their pods.
 * Node has no flock(2), so a `flock` child holds it, running `cat` on a pipe from the runner.
 * However the runner ends, the kernel closes its end of the pipe, `cat` reads the end of its
 * input, and the lock goes with it.
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import type { Socket } from 'node:net';
import { hostname } from 'node:os';
import { dirname, join } from 'node:path';

// The spec repo's checkout, at this path in every environment of the project. Never relative to
// this checkout: a run-slice phase runs the suite in a worktree under /work/scratch.
const SPEC_REPO = '/work/PilotAppSpecs';

// The spec repo's git ignores /.locks/.
const LOCK_FILE = join(SPEC_REPO, '.locks', 'test-suite.lock');

// A full suite holds the lock for about 20 minutes. A wait gives up well inside the 10 minutes an
// agent's command may take at most, so that it reads why the run ended.
const DEFAULT_WAIT_SECONDS = 300;

// How long a run takes the lock before it says that it waits.
const WAIT_NOTICE_MS = 1000;

// The exit code of a run that gave up waiting: EX_TEMPFAIL, try again later.
const LOCK_TIMEOUT_EXIT_CODE = 75;

// flock's exit code when its wait runs out, told apart from flock's own failures.
const FLOCK_TIMEOUT_CODE = 75;

/** The `key: value` lines the holder writes into the lock's file. */
export type HolderNote = Record<string, string>;

interface HeldLock {
  /** Let the lock go before the runner ends: what the runner's end does. */
  release(): void;
}

export class TestSuiteLockTimeout extends Error {
  readonly holder: HolderNote;

  constructor(holder: HolderNote) {
    super('Gave up waiting for the test suite lock');
    this.holder = holder;
  }
}

/** The lock's file, or null where no lock is taken: outside KubeCoder, as in CI, or beside no spec repo. */
export function testSuiteLockFile(env: NodeJS.ProcessEnv = process.env): string | null {
  if (!env.KUBECODER_ENVIRONMENT_ID || !existsSync(SPEC_REPO)) {
    return null;
  }
  return LOCK_FILE;
}

export function readHolderNote(file: string): HolderNote {
  let text = '';
  try {
    text = readFileSync(file, 'utf8');
  } catch {
    // No file yet: no holder has written one.
  }
  const note: HolderNote = {};
  for (const line of text.split('\n')) {
    const separator = line.indexOf(': ');
    if (separator > 0) {
      note[line.slice(0, separator)] = line.slice(separator + 2);
    }
  }
  return note;
}

/**
 * Take the lock on `file`, waiting at most `waitSeconds`, and write `holder` into it once taken.
 * `onWait` hears the holder's note if the lock is not taken at once. Rejects with
 * TestSuiteLockTimeout when the wait runs out.
 */
export async function acquireTestSuiteLock(
  file: string,
  options: { waitSeconds: number; holder: HolderNote; onWait?: (holder: HolderNote) => void }
): Promise<HeldLock> {
  mkdirSync(dirname(file), { recursive: true });
  const wait = options.waitSeconds > 0 ? ['--wait', String(options.waitSeconds)] : ['--nonblock'];
  const child = spawn(
    'flock',
    [...wait, '--conflict-exit-code', String(FLOCK_TIMEOUT_CODE), file, 'sh', '-c', 'echo locked && exec cat'],
    { stdio: ['pipe', 'pipe', 'inherit'] }
  );
  const stdin = child.stdin as Socket;
  const stdout = child.stdout as Socket;

  return await new Promise<HeldLock>((resolvePromise, rejectPromise) => {
    const notice = setTimeout(() => options.onWait?.(readHolderNote(file)), WAIT_NOTICE_MS);

    const onExit = (code: number | null) => {
      clearTimeout(notice);
      if (code === FLOCK_TIMEOUT_CODE) {
        rejectPromise(new TestSuiteLockTimeout(readHolderNote(file)));
      } else {
        rejectPromise(new Error(`flock exited with code ${code ?? 'null'} before it took the test suite lock`));
      }
    };
    child.once('exit', onExit);
    child.once('error', error => {
      clearTimeout(notice);
      rejectPromise(error);
    });

    stdout.once('data', () => {
      clearTimeout(notice);
      child.off('exit', onExit);
      writeFileSync(
        file,
        Object.entries(options.holder)
          .map(([key, value]) => `${key}: ${value}\n`)
          .join('')
      );
      // The held lock never keeps the runner alive: the runner's end is what lets it go.
      child.unref();
      stdin.unref();
      stdout.unref();
      resolvePromise({ release: () => stdin.end() });
    });
  });
}

/**
 * Take the test suite lock for this run, in the runner's process (global setup), and hold it until
 * the runner ends. A run that gives up waiting ends here with LOCK_TIMEOUT_EXIT_CODE, having run
 * nothing. PLAYWRIGHT_SUITE_LOCK_WAIT sets the wait in seconds.
 */
export async function holdTestSuiteLock(): Promise<void> {
  const file = testSuiteLockFile();
  if (!file) {
    return;
  }

  const configured = Number(process.env.PLAYWRIGHT_SUITE_LOCK_WAIT);
  const waitSeconds = process.env.PLAYWRIGHT_SUITE_LOCK_WAIT && Number.isFinite(configured)
    ? configured
    : DEFAULT_WAIT_SECONDS;

  try {
    // Never released here: the runner's end lets it go.
    await acquireTestSuiteLock(file, {
      waitSeconds,
      holder: {
        environment: process.env.KUBECODER_ENVIRONMENT_ID ?? '',
        host: hostname(),
        pid: String(process.pid),
        started: new Date().toISOString(),
      },
      onWait: holder =>
        console.log(
          `⏳ Waiting up to ${formatSeconds(waitSeconds)} for the test suite lock, held by ${describeHolder(holder)}`
        ),
    });
  } catch (error) {
    if (!(error instanceof TestSuiteLockTimeout)) {
      throw error;
    }
    console.error(
      `⛔ Gave up after ${formatSeconds(waitSeconds)} waiting for the test suite lock, held by ` +
        `${describeHolder(error.holder)}. No test ran, so none failed: run the suite again once ` +
        `that run is done (${file}). Exit code ${LOCK_TIMEOUT_EXIT_CODE}.`
    );
    process.exit(LOCK_TIMEOUT_EXIT_CODE);
  }
  console.log(`🔒 Holding the test suite lock (${file})`);
}

export function describeHolder(holder: HolderNote, now: Date = new Date()): string {
  if (!holder.environment) {
    return 'a run that left no note';
  }
  const started = Date.parse(holder.started ?? '');
  const minutes = Number.isNaN(started) ? null : Math.max(0, Math.round((now.getTime() - started) / 60_000));
  const since = minutes === null ? '' : `, running for ${minutes} min`;
  return `the run in ${holder.environment} (pid ${holder.pid ?? '?'} on ${holder.host ?? '?'}${since})`;
}

function formatSeconds(seconds: number): string {
  return seconds > 0 && seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} s`;
}

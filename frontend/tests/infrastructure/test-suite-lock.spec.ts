/**
 * The test suite lock (tests/support/test-suite-lock.ts): one Playwright run at a time across the
 * project's environments, taken in global setup and gone with the runner. No browser and no
 * backend: the plain test of @playwright/test, so that the worker starts no services for it.
 */

import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import {
  acquireTestSuiteLock,
  describeHolder,
  type HolderNote,
  readHolderNote,
  testSuiteLockFile,
  TestSuiteLockTimeout,
} from '../support/test-suite-lock';

const MODULE = resolve(dirname(fileURLToPath(import.meta.url)), '../support/test-suite-lock.ts');

// Invented holders.
const FIRST: HolderNote = { environment: 'playwright-first', host: 'first-host', pid: '101', started: '2026-01-01T10:00:00.000Z' };
const SECOND: HolderNote = { environment: 'playwright-second', host: 'second-host', pid: '202', started: '2026-01-01T10:20:00.000Z' };

function isLocked(file: string): boolean {
  return spawnSync('flock', ['--nonblock', file, 'true']).status !== 0;
}

test.describe('The test suite lock', () => {
  let file: string;
  let dir: string;

  test.beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'test-suite-lock-'));
    file = join(dir, '.locks', 'test-suite.lock');
  });

  test.afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  test('keeps a second run waiting, tells it whose run holds it, and lets it give up', async () => {
    const first = await acquireTestSuiteLock(file, { waitSeconds: 1, holder: FIRST });
    try {
      const heard: HolderNote[] = [];
      const error = await acquireTestSuiteLock(file, {
        waitSeconds: 2,
        holder: SECOND,
        onWait: holder => heard.push(holder),
      }).then(
        () => null,
        (reason: unknown) => reason
      );

      expect(error).toBeInstanceOf(TestSuiteLockTimeout);
      expect((error as TestSuiteLockTimeout).holder).toEqual(FIRST);
      expect(heard).toEqual([FIRST]);
      expect(describeHolder(FIRST, new Date('2026-01-01T10:12:00.000Z'))).toBe(
        'the run in playwright-first (pid 101 on first-host, running for 12 min)'
      );
    } finally {
      first.release();
    }
  });

  test('goes to the next run once the holder lets it go', async () => {
    const first = await acquireTestSuiteLock(file, { waitSeconds: 1, holder: FIRST });
    first.release();

    const second = await acquireTestSuiteLock(file, { waitSeconds: 5, holder: SECOND });
    try {
      expect(readHolderNote(file)).toEqual(SECOND);
    } finally {
      second.release();
    }
  });

  test('dies with a holder that is killed', async () => {
    // A runner of its own, holding the lock until it is killed: Node strips the module's types.
    const script = `
      const lock = await import(${JSON.stringify(MODULE)});
      await lock.acquireTestSuiteLock(${JSON.stringify(file)}, { waitSeconds: 5, holder: ${JSON.stringify(FIRST)} });
      console.log('held');
      setInterval(() => {}, 60_000);
    `;
    const holder = spawn(process.execPath, ['--input-type=module', '-e', script], { stdio: ['ignore', 'pipe', 'pipe'] });
    let stderr = '';
    holder.stderr.on('data', chunk => {
      stderr += chunk.toString();
    });
    try {
      await new Promise<void>((resolvePromise, rejectPromise) => {
        holder.stdout.once('data', () => resolvePromise());
        holder.once('exit', code =>
          rejectPromise(new Error(`the holder exited with code ${code} before it held the lock:\n${stderr}`))
        );
      });
      expect(isLocked(file)).toBe(true);
    } finally {
      holder.kill('SIGKILL');
    }

    await expect.poll(() => isLocked(file), { timeout: 5000 }).toBe(false);
  });

  test('is held by this run, taken in its runner', () => {
    const lockFile = testSuiteLockFile();
    test.skip(!lockFile, 'no lock outside KubeCoder');

    expect(isLocked(lockFile!)).toBe(true);
    const note = readHolderNote(lockFile!);
    expect(note.environment).toBe(process.env.KUBECODER_ENVIRONMENT_ID);
    // The workers are the runner's children.
    expect(note.pid).toBe(String(process.ppid));
  });

  test('is taken only inside KubeCoder', () => {
    expect(testSuiteLockFile({})).toBeNull();
  });
});

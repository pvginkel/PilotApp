/**
 * The worker's KubeCoder controller, for a spec: the fake its backend serves itself under
 * /api/testing/controller (design 2 §12; backend-env-extensions.ts points the backend at it). The
 * environments are those Pilot's starts create in it, read from the work item
 * (`Projects.environment()`); a spec drives them and their headless sessions through the fake's
 * verbs, POST /api/testing/controller/fake/<verb>, which take no sign-in. Pilot's headless sessions
 * in an environment are `claude-1`, `claude-2`, … in the order Pilot creates them there. The lines a
 * turn plays are the backend suite's invented ones (`rawTurn()`). A process in an environment writes,
 * deletes and reads its files as the controller's file endpoints serve them.
 *
 * The controller unreachable is a state the backend holds, which the gold bar reads (GET
 * /api/conditions): `outage()` returns once the backend reads it as asked. The fake's verbs that
 * act on every environment hold across the worker's specs, so the fixture restores the controller
 * after a spec that changed it (`restore()`): every spec starts with the controller answering, the
 * node under its cap and a create settling `running`.
 */

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, type APIRequestContext, type APIResponse, type Page, type PlaywrightWorkerArgs } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';
import { makeUnique } from './helpers';

type Condition = components['schemas']['ConditionsSchema.6c014b4.ConditionSchema'];

type EnvironmentStatus = 'provisioning' | 'starting' | 'running' | 'stopping' | 'stopped' | 'deleting' | 'error';
/** How a turn ends: `claude`'s own result, a failed one, an interrupt, or the spawn failing or the session ending, which the worker alone reports. */
type FinishOutcome = 'success' | 'error' | 'interrupted' | 'spawn-failure' | 'ended';
/** How a call goes unanswered while the controller is down: its connection closed with no answer, or an ingress's `502` page. */
type Unanswered = 'none' | 'ingress';
/** The backend suite's invented turns, in `backend/tests/fixtures/raw/`. */
type RawTurn = 'turn_text' | 'turn_tool' | 'turn_subagent';

// The backend reads the controller answering again at its fleet stream's reconnect, whose
// backoff doubles from 1 s to 30 s while the outage holds.
const OUTAGE_TIMEOUT_MS = 45_000;

// The supervisor counts each restart of the fleet consumer's loop as it begins its reconnect.
const FLEET_RESTARTS = /^pilot_job_restarts_total\{job="fleet"\} (\S+)$/m;

const BACKEND_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..', process.env.BACKEND_ROOT || '../backend');

/** An invented turn's lines, as `claude` prints them. */
export function rawTurn(name: RawTurn): string[] {
  const text = readFileSync(resolve(BACKEND_ROOT, 'tests/fixtures/raw', `${name}.jsonl`), 'utf-8');
  return text.split('\n').filter((line) => line !== '');
}

/** The conditions the backend reads, through a request context of the harness's own, signed in. */
export class Conditions {
  private constructor(private readonly request: APIRequestContext) {}

  static async open(playwright: PlaywrightWorkerArgs['playwright'], backendUrl: string): Promise<Conditions> {
    const request = await playwright.request.newContext({ baseURL: backendUrl });
    const response = await request.post('/api/testing/auth/session', {
      data: { subject: makeUnique('harness'), name: 'Harness', roles: ['editor'] },
    });
    expect(response.ok(), await response.text()).toBe(true);
    return new Conditions(request);
  }

  async read(): Promise<Condition[]> {
    const response = await this.request.get('/api/conditions');
    expect(response.status(), await response.text()).toBe(200);
    return ((await response.json()) as { conditions: Condition[] }).conditions;
  }

  /** Returns once the backend reads the controller unreachable (`on`) or answering. */
  async outage(on: boolean): Promise<void> {
    await expect
      .poll(async () => (await this.read()).some((condition) => condition.code === 'outage'), { timeout: OUTAGE_TIMEOUT_MS })
      .toBe(on);
  }

  /** How many times the backend's fleet consumer has restarted its stream. */
  async fleetRestarts(): Promise<number> {
    const response = await this.request.get('/metrics');
    expect(response.status(), await response.text()).toBe(200);
    const match = FLEET_RESTARTS.exec(await response.text());
    return match === null ? 0 : Number(match[1]);
  }

  /** Returns once the fleet stream has restarted more than `restarts` times and the backend reads the controller answering. */
  async reconnected(restarts: number): Promise<void> {
    await expect.poll(() => this.fleetRestarts(), { timeout: OUTAGE_TIMEOUT_MS }).toBeGreaterThan(restarts);
    await this.outage(false);
  }

  async dispose(): Promise<void> {
    await this.request.dispose();
  }
}

export class Controller {
  private unanswered = false;
  private nodeCapped = false;
  private createsHeld = false;

  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
    private readonly conditions: Conditions,
  ) {}

  /** `claude` prints `lines` in the session's turn: an open stream sends them. Answers each line's offset. */
  async play(envId: string, session: string, lines: string[]): Promise<number[]> {
    const response = await this.verb('play', { env_id: envId, name: session, lines }, 200);
    return (await response.json()) as number[];
  }

  /** The session's turn in flight ends as `outcome` has it, with `result` as its result's text. */
  async finish(envId: string, session: string, outcome: FinishOutcome = 'success', result = ''): Promise<void> {
    await this.verb('finish', { env_id: envId, name: session, outcome, result });
  }

  /**
   * Every open stream ends at once, as a dropped connection does, the fleet stream's included. The
   * backend reads the controller unreachable until its fleet stream reconnects, and this returns
   * once it has, unless the controller is unreachable (`outage(true)`).
   */
  async dropStreams(): Promise<void> {
    const restarts = await this.conditions.fleetRestarts();
    await this.verb('drop-streams', {});
    if (!this.unanswered) await this.conditions.reconnected(restarts);
  }

  /** A process in the environment writes `content` as the file at `path`, whatever its status. */
  async putFile(envId: string, path: string, content: string): Promise<void> {
    await this.verb('put-file', { env_id: envId, path, content });
  }

  /** A process in the environment deletes the file at `path`. */
  async removeFile(envId: string, path: string): Promise<void> {
    await this.verb('remove-file', { env_id: envId, path });
  }

  /** The text of the file at `path` in the environment; null when there is none. */
  async fileText(envId: string, path: string): Promise<string | null> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/controller/fake/file-text`, {
      data: { env_id: envId, path },
    });
    expect([200, 204], await response.text()).toContain(response.status());
    return response.status() === 204 ? null : ((await response.json()) as string);
  }

  /** The pod's containers restart: its sessions are gone, and the environment reads `starting` until `setStatus(envId, 'running')`. */
  async restart(envId: string): Promise<void> {
    await this.verb('restart', { env_id: envId });
  }

  /** The environment reaches `status`: `stopped` or `deleting` is a stop made elsewhere. */
  async setStatus(envId: string, status: EnvironmentStatus): Promise<void> {
    await this.verb('set-status', { env_id: envId, status });
  }

  /** What a start or a reset brings the environment to at once; null holds it `starting` until `setStatus()`. */
  async settleStarts(envId: string, status: EnvironmentStatus | null): Promise<void> {
    await this.verb('settle-starts', { env_id: envId, status });
  }

  /**
   * What a create brings its environment to at once, and that environment's starts and resets
   * after it (`settleStarts()`); null holds it `provisioning` until `setStatus()`.
   */
  async settleCreates(status: EnvironmentStatus | null): Promise<void> {
    await this.verb('settle-creates', { status });
    this.createsHeld = status !== 'running';
  }

  /** The environment is gone from the fleet, its sessions with it. */
  async removeEnvironment(envId: string): Promise<void> {
    await this.verb('remove-environment', { env_id: envId });
  }

  /** The node at its cap, or (`on` false) under it: a create, a start and a reset are `409 admission-blocked`. */
  async capped(on = true): Promise<void> {
    await this.verb('capped', { on });
    this.nodeCapped = on;
  }

  /** The environment's worker unreachable, or (`on` false) reached again: its calls are `502 worker-unreachable`. */
  async unreachable(envId: string, on = true): Promise<void> {
    await this.verb('unreachable', { env_id: envId, on });
  }

  /**
   * The controller unreachable as a whole, every call unanswered and every stream ended, or (`on`
   * false) answering again; returns once the backend reads it so.
   */
  async outage(on: boolean, answer?: Unanswered): Promise<void> {
    if (on) this.unanswered = true;
    await this.verb('outage', answer === undefined ? { on } : { on, answer });
    await this.conditions.outage(on);
    this.unanswered = on;
  }

  /** The controller as every spec starts with it, after a spec that changed it. */
  async restore(): Promise<void> {
    if (this.unanswered) await this.outage(false);
    if (this.nodeCapped) await this.capped(false);
    if (this.createsHeld) await this.settleCreates('running');
  }

  /** A verb of the fake's, which answers `204`, or `200` with what it returns. */
  private async verb(verb: string, args: Record<string, unknown>, status = 204): Promise<APIResponse> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/controller/fake/${verb}`, { data: args });
    expect(response.status(), await response.text()).toBe(status);
    return response;
  }
}

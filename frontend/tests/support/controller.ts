/**
 * The worker's KubeCoder controller, for a spec: the fake its backend serves itself under
 * /api/testing/controller (design 2 §12; backend-env-extensions.ts points the backend at it). A
 * spec gives it environments and drives them and their headless sessions through the fake's
 * verbs, POST /api/testing/controller/fake/<verb>, which take no sign-in. Pilot's headless sessions
 * in an environment are `claude-1`, `claude-2`, … in the order Pilot creates them there. The lines a
 * turn plays are the backend suite's invented ones (`rawTurn()`).
 *
 * The controller unreachable is a state the backend holds, which the gold bar reads (GET
 * /api/conditions): `outage()` returns once the backend reads it as asked, and the fixture answers
 * again after a spec that left it unreachable, so that every spec starts with the controller
 * answering.
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

  async dispose(): Promise<void> {
    await this.request.dispose();
  }
}

export class Controller {
  private unanswered = false;

  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
    private readonly conditions: Conditions,
  ) {}

  /** An environment of the fleet, `stopped` unless `status` says otherwise, named by its id unless `name` is given; answers its id. */
  async environment({ name, status = 'stopped' }: { name?: string; status?: EnvironmentStatus } = {}): Promise<string> {
    const id = makeUnique('env');
    await this.verb('add-environment', { env_id: id, name: name ?? id, status });
    return id;
  }

  /** `claude` prints `lines` in the session's turn: an open stream sends them. Answers each line's offset. */
  async play(envId: string, session: string, lines: string[]): Promise<number[]> {
    const response = await this.verb('play', { env_id: envId, name: session, lines }, 200);
    return (await response.json()) as number[];
  }

  /** The session's turn in flight ends as `outcome` has it, with `result` as its result's text. */
  async finish(envId: string, session: string, outcome: FinishOutcome = 'success', result = ''): Promise<void> {
    await this.verb('finish', { env_id: envId, name: session, outcome, result });
  }

  /** Every open stream ends at once, as a dropped connection does, the fleet stream's included. */
  async dropStreams(): Promise<void> {
    await this.verb('drop-streams', {});
  }

  /** The pod's containers restart: its sessions are gone, and the environment reads `starting` until `setStatus(envId, 'running')`. */
  async restart(envId: string): Promise<void> {
    await this.verb('restart', { env_id: envId });
  }

  /** The environment reaches `status`: `stopped` or `deleting` is a stop made elsewhere. */
  async setStatus(envId: string, status: EnvironmentStatus): Promise<void> {
    await this.verb('set-status', { env_id: envId, status });
  }

  /** What a start brings the environment to at once; null holds it `starting` until `setStatus()`. */
  async settleStarts(envId: string, status: EnvironmentStatus | null): Promise<void> {
    await this.verb('settle-starts', { env_id: envId, status });
  }

  /** The environment is gone from the fleet, its sessions with it. */
  async removeEnvironment(envId: string): Promise<void> {
    await this.verb('remove-environment', { env_id: envId });
  }

  /** The node at its cap, or (`on` false) under it: a start is `409 admission-blocked`. */
  async capped(envId: string, on = true): Promise<void> {
    await this.verb('capped', { env_id: envId, on });
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

  /** The controller answering again after a spec that left it unreachable. */
  async answerAgain(): Promise<void> {
    if (this.unanswered) await this.outage(false);
  }

  /** A verb of the fake's, which answers `204`, or `200` with what it returns. */
  private async verb(verb: string, args: Record<string, unknown>, status = 204): Promise<APIResponse> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/controller/fake/${verb}`, { data: args });
    expect(response.status(), await response.text()).toBe(status);
    return response;
  }
}

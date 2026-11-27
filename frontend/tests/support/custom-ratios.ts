/**
 * The dashboard's custom ratios as a spec makes them (F155.1, F155.3): a person's, for everyone,
 * through the API, as the signed-in person, each under a name of the spec's own, since every spec of
 * a worker shares its record; and the workflow's, loaded from the entries of its file by a service
 * user of its own on a connection of its own, as the workflow's command loads them. A load replaces
 * the workflow's ratios whole, so the spec's are taken away again as it ends.
 */

import { randomUUID } from 'node:crypto';
import { expect, type APIRequestContext, type Page, type PlaywrightWorkerArgs } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';
import { makeUniqueToken } from './helpers';

type Made = components['schemas']['CustomRatioSchema.b67cf98'];
type Write = components['schemas']['CustomRatioWriteSchema.ddf95d6'];
type LoadedRatio = components['schemas']['WorkflowLoadSchema.ddf95d6.WorkflowRatioSchema'];

export class CustomRatios {
  private loader: APIRequestContext | null = null;

  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
    private readonly playwright: PlaywrightWorkerArgs['playwright'],
  ) {}

  /** A person's ratio made; answers it as the server holds it. */
  async make(ratio: Write): Promise<Made> {
    const response = await this.page.request.post(`${this.backendUrl}/api/dashboard/custom-ratios`, { data: ratio });
    expect(response.status(), await response.text()).toBe(201);
    return (await response.json()) as Made;
  }

  /** The workflow's file loaded with these ratios and no views. */
  async loadWorkflow(ratios: LoadedRatio[]): Promise<void> {
    if (this.loader === null) {
      const token = makeUniqueToken(6);
      const subject = `service-${randomUUID()}`;
      const made = await this.page.request.post(`${this.backendUrl}/api/testing/service-users`, { data: { handle: `fleet-${token}`, name: 'Example fleet', subject } });
      expect(made.status(), await made.text()).toBe(201);
      this.loader = await this.playwright.request.newContext({ baseURL: this.backendUrl });
      const signedIn = await this.loader.post('/api/testing/auth/session', { data: { subject, name: 'Example fleet', roles: ['editor'] } });
      expect(signedIn.ok(), await signedIn.text()).toBe(true);
    }
    const loaded = await this.loader.put('/api/dashboard/workflow', { data: { views: [], ratios } });
    expect(loaded.status(), await loaded.text()).toBe(200);
  }

  async dispose(): Promise<void> {
    if (this.loader === null) return;
    await this.loadWorkflow([]);
    await this.loader.dispose();
  }
}

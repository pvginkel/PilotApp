/**
 * The brain's waits for a spec (F27): added by a project's session as `add_item` adds one, placed
 * now or at a time before now (POST /api/testing/projects/<id>/waits); fired by a card's State
 * change, delivered as YouTrack's Webhook Triggers app posts it, past the token the endpoint checks
 * (POST /api/testing/tracker-events/youtrack), or by the waits' timer's tick, run now
 * (POST /api/testing/waits/due); their run placed now (POST /api/testing/waits/<id>/run), which
 * starts in the store's environment of the fake controller, `chats.ts` readying it; and closed with
 * a note as Pilot's `mark` closes one, by the wait's latest run briefed
 * (POST /api/testing/waits/<id>/close). The suite's backends wait a day before the batcher places a
 * run (backend-env-extensions.ts), so a firing stays pending until a spec places its run.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';

type WaitSpec = components['schemas']['InventedWaitCreateSchema.6d6b324'];

/** A card's change of state, as the tracker reports it. */
interface Transition {
  card: string;
  from: string;
  to: string;
  by: string;
}

export class Waits {
  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
  ) {}

  /** A wait the project's session adds; answers its id. */
  async add(projectId: string, spec: WaitSpec): Promise<string> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/projects/${projectId}/waits`, { data: spec });
    expect(response.status(), await response.text()).toBe(201);
    return ((await response.json()) as { id: string }).id;
  }

  /** A card's State change, as YouTrack posts it; answers how many waits it fired. */
  async transition({ card, from, to, by }: Transition): Promise<number> {
    const now = new Date();
    const delivery = {
      event: 'issueUpdated',
      timestamp: now.toISOString(),
      id: card,
      summary: 'An invented card',
      description: '',
      project: { key: '0-1', name: 'Invented', shortName: card.split('-')[0] },
      updated: now.getTime(),
      updatedBy: { login: by, fullName: 'An Invented Person', email: `${by}@example.com` },
      changedFields: [{ name: 'State', oldValue: { name: from, presentation: from }, value: { name: to, presentation: to } }],
    };
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/tracker-events/youtrack`, { data: delivery });
    expect(response.status(), await response.text()).toBe(200);
    return ((await response.json()) as { fired: number }).fired;
  }

  /** The waits' timer's tick, now: every open timed wait past its due time fires; answers how many. */
  async due(): Promise<number> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/waits/due`);
    expect(response.status(), await response.text()).toBe(200);
    return ((await response.json()) as { fired: number }).fired;
  }

  /** The wait's run, placed now with every firing pending; answers its work item's id. */
  async run(waitId: string): Promise<string> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/waits/${waitId}/run`);
    expect(response.status(), await response.text()).toBe(201);
    return ((await response.json()) as { id: string }).id;
  }

  /** Pilot's close of the wait with its note, by its latest run briefed. */
  async close(waitId: string, note: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/waits/${waitId}/close`, { data: { note } });
    expect(response.status(), await response.text()).toBe(204);
  }
}

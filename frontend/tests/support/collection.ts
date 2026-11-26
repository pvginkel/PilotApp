/**
 * What a collector gives Pilot, as a spec drives it: an invented scenario's conversations, each
 * published whole, its last moment now, with what Pilot holds of those it ran on the projects the
 * spec gives (POST /api/testing/scenarios, F122.6), a second load replacing the first; and a walk's
 * end (POST /api/testing/walks, F152.14), which sends every person's connections
 * `collection_changed` where a transcript was published since the walk before, a load's among them.
 *
 * Two scenarios: `supper`, the invented story, and `tally`, all of it Pilot's, whose figures the
 * dashboard's specs assert (`TALLY`). The tally's Turns by a person are Ada's and Ben's, whom the seed
 * holds.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';

type ScenarioLoad = components['schemas']['InventedScenarioCreateSchema.6d6b324'];
type Scenario = components['schemas']['InventedScenarioSchema.6d6b324'];
type Walk = components['schemas']['InventedWalkSchema.6d6b324'];

/**
 * The tally's figures over all time on the two projects it is loaded on, as the dashboard's rows
 * answer them (`backend/tests/dashboard/test_tally.py` pins them). Its 16 Calls and 5 Turns of
 * Pilot's span the 4,040 s before its load.
 */
export const TALLY = {
  cost: 2.285275,
  calls: 16,
  turns: 5,
  /** Its `bike-log`'s cost, Calls and Turns: the job. */
  bikeLog: [1.178595, 3, 1],
  /** Its `recipe-box`'s: the work item's run and the chat. */
  recipeBox: [1.10668, 13, 4],
} as const;

export class Collection {
  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
  ) {}

  /**
   * The scenario loaded, `projects` the project that stands for each of its projects Pilot ran a session
   * on, by the scenario's name of it: `recipe-box` for `supper`, `recipe-box` and `bike-log` for
   * `tally`. Answers its transcripts in the scenario's order, each with the adopted project that adopted
   * it; `supper`'s group's is made by the stage's service user (`people.serviceUser()`).
   */
  async loadScenario(scenario: ScenarioLoad['scenario'], projects: ScenarioLoad['projects']): Promise<Scenario['transcripts']> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/scenarios`, { data: { scenario, projects } });
    expect(response.status(), await response.text()).toBe(201);
    return ((await response.json()) as Scenario).transcripts;
  }

  /** A walk's end, as a collector tells it; answers whether its event was sent. */
  async walk(): Promise<Walk> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/walks`);
    expect(response.status(), await response.text()).toBe(201);
    return (await response.json()) as Walk;
  }
}

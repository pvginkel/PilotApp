/**
 * The dashboard's saved views as a spec makes them (F155.1): for everyone, through the API, as the
 * signed-in person, each under a name of the spec's own, since every spec of a worker shares its
 * record.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';

type Saved = components['schemas']['SaveViewResponseSchema.ddf95d6'];

export class SavedViews {
  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
  ) {}

  /** A view saved under `name`, `state` its state; answers its id. */
  async save(name: string, state: string): Promise<string> {
    const response = await this.page.request.post(`${this.backendUrl}/api/dashboard/saved-views`, { data: { name, state } });
    expect(response.status(), await response.text()).toBe(201);
    return ((await response.json()) as Saved).view.id;
  }

  /** The view removed, as another person removes it. */
  async remove(id: string): Promise<void> {
    const response = await this.page.request.delete(`${this.backendUrl}/api/dashboard/saved-views/${id}`);
    expect(response.status(), await response.text()).toBe(204);
  }
}

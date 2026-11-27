/**
 * The dashboard's saved views as a spec makes them (F155.1): for everyone, through the API, as the
 * signed-in person, each under a name of the spec's own, since every spec of a worker shares its
 * record.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';

type Saved = components['schemas']['SaveViewResponseSchema.ddf95d6'];
type Catalogue = components['schemas']['CatalogueResponseSchema.b67cf98'];
type SavedView = components['schemas']['CatalogueResponseSchema.b67cf98.SavedViewSchema'];

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

  /** The views a person saved under `name`, as the server holds them now: one at most. */
  async named(name: string): Promise<SavedView[]> {
    const response = await this.page.request.get(`${this.backendUrl}/api/dashboard/catalogue?part=stored`);
    expect(response.status(), await response.text()).toBe(200);
    return ((await response.json()) as Catalogue).saved_views!.filter((view) => !view.system && view.name === name);
  }

  /** The view removed, as another person removes it. */
  async remove(id: string): Promise<void> {
    const response = await this.page.request.delete(`${this.backendUrl}/api/dashboard/saved-views/${id}`);
    expect(response.status(), await response.text()).toBe(204);
  }
}

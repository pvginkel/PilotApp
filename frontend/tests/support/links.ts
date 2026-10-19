/**
 * What links in text, for a spec: the deployment's link settings, set on the worker's backend
 * through PUT /api/testing/links, and the record's environments, whose names link. The fixture
 * unsets the settings after the spec, so every other spec meets them unset, the default.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';

type LinkSettings = components['schemas']['LinkSettingsSchema.fb10421'];

export class Links {
  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
  ) {}

  /** The link settings; a setting left out is unset. */
  async set(settings: LinkSettings): Promise<void> {
    const response = await this.page.request.put(`${this.backendUrl}/api/testing/links`, { data: settings });
    expect(response.status(), await response.text()).toBe(200);
  }

  /** An environment on the record, which text names by `name`. */
  async environment(id: string, name: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/environments`, { data: { id, name } });
    expect(response.status(), await response.text()).toBe(201);
  }
}

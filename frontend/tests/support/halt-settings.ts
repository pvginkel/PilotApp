/**
 * What each usage halt does to the work items (F135.6), for a spec: set on the worker's backend
 * through PUT /api/testing/halt-settings, for the halts decided from then on. The fixture gives the
 * backend back the settings it booted with after the spec (tests/support/backend-env-extensions.ts),
 * once the usage is under the limits again, so every other spec meets them.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';

type Settings = components['schemas']['HaltSettingsSchema.c4ded92'];

export class HaltSettings {
  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
  ) {}

  /** The halts' settings; a setting left out is the one the backend booted with. */
  async set(settings: Settings): Promise<void> {
    const response = await this.page.request.put(`${this.backendUrl}/api/testing/halt-settings`, { data: settings });
    expect(response.status(), await response.text()).toBe(200);
  }
}

/**
 * The dashboard engine's timeout (F154.5) and its hold, for a spec: set on the worker's backend
 * through PUT /api/testing/dashboard-bounds, for the reads that start from then on. The fixture gives
 * the backend back the timeout it booted with and no hold after the spec, so every other spec meets
 * them.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';

type Bounds = components['schemas']['DashboardBoundsSchema.467cb1a'];

/** Shorter than any read takes: the engine refuses each at its start, `QUERY_TIMEOUT`. */
export const NONE_LEFT = 1e-9;

export class DashboardBounds {
  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
  ) {}

  /** The engine's timeout, left out the one the backend booted with; and its hold, By's counts waiting after their first fact until the next `set`. */
  async set(bounds: Bounds): Promise<void> {
    const response = await this.page.request.put(`${this.backendUrl}/api/testing/dashboard-bounds`, { data: bounds });
    expect(response.status(), await response.text()).toBe(200);
  }
}

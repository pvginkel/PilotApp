/**
 * The store's update for a spec (F144.5): `make()` sets the hold on the store's work across the
 * worker's backend, as `update-store` does, and `lift()` asks its lift, as its `--lift` does, both
 * through POST /api/testing/store-update. The server takes the update up at its timer's next tick:
 * it stops the store's jobs and chats by Pilot, resets the store in the fake, which clears its tree
 * (`reset()`), and then waits for a manifest from the store's sidecar, which no sidecar posts under
 * Playwright, so the hold stands until its lift. Every spec of the worker shares its backend: the
 * fixture asks the lift of an update a spec left standing, and waits for it.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';
import type { Chats } from './chats';
import type { Conditions } from './controller';

type Update = components['schemas']['InventedStoreUpdateSchema.6d6b324'];

/** Two of the backend's scheduler ticks (SCHEDULER_TICK_SECONDS, 10 s): its timer takes an update up and tells the browsers of it. */
export const TICKS_MS = 20_000;

export class StoreUpdate {
  private standing = false;

  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
    private readonly conditions: Conditions,
    private readonly chats: Chats,
  ) {}

  /** An update made, its hold standing: the store in the fake first, which its reset needs. */
  async make(): Promise<Update> {
    await this.chats.stock();
    const update = await this.post(false, 201);
    this.standing = true;
    return update;
  }

  /** Returns once the update's reset has cleared the store's tree. */
  async reset(): Promise<void> {
    await expect.poll(() => this.chats.stocked(), { timeout: TICKS_MS }).toBe(false);
  }

  /** Its lift asked: returns once the update is lifted, the hold gone. */
  async lift(): Promise<void> {
    await this.post(true, 200);
    this.standing = false;
    await expect
      .poll(async () => (await this.conditions.read()).some((condition) => condition.code === 'store_update'), { timeout: TICKS_MS })
      .toBe(false);
  }

  async restore(): Promise<void> {
    if (this.standing) await this.lift();
  }

  private async post(lift: boolean, status: number): Promise<Update> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/store-update`, { data: { lift } });
    expect(response.status(), await response.text()).toBe(status);
    return (await response.json()) as Update;
  }
}

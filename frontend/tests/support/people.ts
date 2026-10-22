/**
 * Signing a spec in as a fresh person: at their first sign-in, or with a handle chosen through
 * POST /api/people/self/handle, the path the handle step takes. A test session writes no person;
 * the handle puts them on the record, in the lowest free avatar slot.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';
import type { AuthFactory } from './helpers/auth-factory';
import { makeUnique } from './helpers';

type Self = components['schemas']['SelfResponseSchema.d1d9f70'];

interface FirstSignIn {
  /** The token's name; null for a token that carries none. */
  name?: string | null;
}

interface SignIn {
  name?: string;
  handle?: string;
}

export class People {
  constructor(
    private readonly page: Page,
    private readonly auth: AuthFactory,
    private readonly backendUrl: string,
  ) {}

  /** A fresh person signed in for the first time: no handle chosen, no slot taken. */
  async firstSignIn({ name = 'Test Person' }: FirstSignIn = {}): Promise<void> {
    await this.auth.createSession({ name, roles: ['editor'] });
  }

  /** A fresh person who has chosen their handle, as the record holds them. */
  async signIn({ name = 'Test Person', handle = makeUnique('p', 8) }: SignIn = {}): Promise<Self> {
    await this.firstSignIn({ name });
    const response = await this.page.request.post(`${this.backendUrl}/api/people/self/handle`, {
      data: { handle },
    });
    expect(response.status(), await response.text()).toBe(201);
    return (await response.json()) as Self;
  }

  /** Another person on the record, who holds `handle`, named `name` or by the handle; the spec stays signed in as it was. */
  async other(handle: string, name?: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/people`, { data: { handle, name } });
    expect(response.status(), await response.text()).toBe(201);
  }

  /** The signed-in person as the API reads them. */
  async self(): Promise<Self> {
    const response = await this.page.request.get(`${this.backendUrl}/api/people/self`);
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as Self;
  }
}

/**
 * Signing a spec in as a fresh person: at their first sign-in, or with a handle chosen through
 * POST /api/people/self/handle, the path the handle step takes. A test session writes no person;
 * the handle puts them on the record, in the lowest free avatar slot. A session without the editor
 * role, for the API's refusals.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';
import type { AuthFactory } from './helpers/auth-factory';
import { makeUnique } from './helpers';
import { PageFetches } from './network';

type Self = components['schemas']['SelfResponseSchema.d1d9f70'];

interface FirstSignIn {
  /** The token's name; null for a token that carries none. */
  name?: string | null;
  /** The token's subject, a fresh one's by default: the same subject signs the same person in again. */
  subject?: string;
}

interface SignIn {
  name?: string;
  handle?: string;
  subject?: string;
}

export class People {
  private readonly fetches: PageFetches;

  constructor(
    private readonly page: Page,
    private readonly auth: AuthFactory,
    private readonly backendUrl: string,
  ) {
    this.fetches = new PageFetches(page);
  }

  /** A fresh person signed in for the first time: no handle chosen, no slot taken. */
  async firstSignIn({ name = 'Test Person', subject }: FirstSignIn = {}): Promise<void> {
    await this.auth.createSession({ subject, name, roles: ['editor'] });
  }

  /**
   * The browser's session swapped for one without the editor role, the same subject's or a fresh
   * one's: every fetch the page sent before the call lands first, under the old session, and every
   * one it sent during the swap before the call returns. A read the window's focus asks for while
   * one of the same query is under way is that read: TanStack Query refetches on focus with
   * `cancelRefetch: false`.
   */
  async withoutRole({ name = 'Test Person', subject }: FirstSignIn = {}): Promise<void> {
    await this.fetches.landed();
    await this.auth.createSession({ subject, name, roles: [] });
    await this.fetches.landed();
  }

  /** A fresh person who has chosen their handle, as the record holds them. */
  async signIn({ name = 'Test Person', handle = makeUnique('p', 8), subject }: SignIn = {}): Promise<Self> {
    await this.firstSignIn({ name, subject });
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

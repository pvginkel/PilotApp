/**
 * Projects on the record for a spec: made in the standing it needs through
 * POST /api/testing/projects, changed through the API the project menu uses, and read as the
 * lists read them. Every list also holds the seed's projects and those earlier specs of the
 * worker made.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';

type ProjectSpec = components['schemas']['InventedProjectCreateSchema.6d6b324'];
type ProjectTab = components['schemas']['ProjectListResponseSchema.e86ccd6.ProjectTabSchema'];
type TransitionKind = components['schemas']['TransitionRequestSchema.e86ccd6']['kind'];

export class Projects {
  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
  ) {}

  /** A project in the standing given; answers its id. */
  async make(spec: ProjectSpec): Promise<string> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/projects`, { data: spec });
    expect(response.status(), await response.text()).toBe(201);
    return ((await response.json()) as { id: string }).id;
  }

  /** The project list's tabs, or the archived projects', as the signed-in person reads them. */
  async list({ archived = false } = {}): Promise<ProjectTab[]> {
    const response = await this.page.request.get(`${this.backendUrl}/api/projects?archived=${archived}`);
    expect(response.status(), await response.text()).toBe(200);
    return ((await response.json()) as { projects: ProjectTab[] }).projects;
  }

  /** A transition by the signed-in person. */
  async transition(id: string, kind: TransitionKind): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/projects/${id}/transitions`, { data: { kind } });
    expect(response.status(), await response.text()).toBe(201);
  }
}

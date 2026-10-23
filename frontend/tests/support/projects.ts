/**
 * Projects on the record for a spec: made in the standing it needs through
 * POST /api/testing/projects, changed through the API the project menu uses, and read as the
 * lists read them. Every list also holds the seed's projects and those earlier specs of the
 * worker made. A project made with a session has items placed on its timeline as Pilot places
 * them, and saves of them as Pilot's (POST /api/testing/projects/<id>/items and
 * /api/testing/items/<id>/saves), its session's turn ended and a document it settled whole marked
 * Done by Pilot; they are answered through the items API.
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';
import { makeUnique } from './helpers';

type ProjectSpec = components['schemas']['InventedProjectCreateSchema.6d6b324'];
type ProjectTab = components['schemas']['ProjectListResponseSchema.e86ccd6.ProjectTabSchema'];
type ProjectHead = components['schemas']['ProjectHeadSchema.e86ccd6'];
type TransitionKind = components['schemas']['TransitionRequestSchema.e86ccd6']['kind'];
type ItemSpec = components['schemas']['InventedItemCreateSchema.6d6b324'];
type Save = components['schemas']['InventedSaveSchema.6d6b324'];
type Timeline = components['schemas']['TimelineSchema.1fdd8ae'];
type Block = components['schemas']['TimelineSchema.1fdd8ae.BlockSchema'];
type BlockPart = components['schemas']['TimelineSchema.1fdd8ae.BlockPartSchema'];

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

  /** A project whose session, in an environment of its own, places its items; answers its id. */
  async makeWithSession(spec: Omit<ProjectSpec, 'environment_id'>): Promise<string> {
    const environment = makeUnique('env');
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/environments`, {
      data: { id: environment, name: environment },
    });
    expect(response.status(), await response.text()).toBe(201);
    return this.make({ ...spec, environment_id: environment });
  }

  /** An item the project's session places, born from its text; answers its id. */
  async place(projectId: string, spec: ItemSpec): Promise<string> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/projects/${projectId}/items`, { data: spec });
    expect(response.status(), await response.text()).toBe(201);
    return ((await response.json()) as { id: string }).id;
  }

  /** A save of the item's text by the project's session: held for a fault, or published. */
  async save(itemId: string, text: string): Promise<Save> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/items/${itemId}/saves`, { data: { text } });
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as Save;
  }

  /** The project's session's turn ends, as the relay ends it: no text is being written, and a change is an edit. */
  async endTurn(projectId: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/projects/${projectId}/turn-ends`);
    expect(response.status(), await response.text()).toBe(204);
  }

  /** Pilot marks Done a document whose every block it answered or deferred. */
  async doneByPilot(itemId: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/items/${itemId}/done`);
    expect(response.status(), await response.text()).toBe(204);
  }

  /** The signed-in person's answer to a block, with a note. */
  async answer(itemId: string, blockId: string, answer: string, note?: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/items/${itemId}/blocks/${blockId}/answer`, {
      data: { answer, note },
    });
    expect(response.status(), await response.text()).toBe(204);
  }

  /** The signed-in person marks an action Done, with what they paste back. */
  async markDone(itemId: string, blockId: string, note?: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/items/${itemId}/blocks/${blockId}/done`, {
      data: { note },
    });
    expect(response.status(), await response.text()).toBe(204);
  }

  /** The signed-in person sends a document's answers: its Done. */
  async send(itemId: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/items/${itemId}/done`);
    expect(response.status(), await response.text()).toBe(204);
  }

  /** The signed-in person undoes an item's answer or mark. */
  async undo(itemId: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/items/${itemId}/undo`);
    expect(response.status(), await response.text()).toBe(204);
  }

  /** A project's timeline, as the signed-in person reads it. */
  async timeline(id: string): Promise<Timeline> {
    const response = await this.page.request.get(`${this.backendUrl}/api/projects/${id}/timeline`);
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as Timeline;
  }

  /** A one-ask item's block, as the signed-in person reads the project's timeline. */
  async block(projectId: string, itemId: string): Promise<Block> {
    const item = (await this.timeline(projectId)).items.find((each) => each.id === itemId)!;
    return (item.body!.find((part) => part.type === 'block') as BlockPart).block;
  }

  /** The project list's tabs, or the archived projects', as the signed-in person reads them. */
  async list({ archived = false } = {}): Promise<ProjectTab[]> {
    const response = await this.page.request.get(`${this.backendUrl}/api/projects?archived=${archived}`);
    expect(response.status(), await response.text()).toBe(200);
    return ((await response.json()) as { projects: ProjectTab[] }).projects;
  }

  /** A project's head, as the signed-in person reads it. */
  async head(id: string): Promise<ProjectHead> {
    const response = await this.page.request.get(`${this.backendUrl}/api/projects/${id}`);
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as ProjectHead;
  }

  /** A transition by the signed-in person. */
  async transition(id: string, kind: TransitionKind): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/projects/${id}/transitions`, { data: { kind } });
    expect(response.status(), await response.text()).toBe(201);
  }
}

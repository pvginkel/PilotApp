/**
 * Projects on the record for a spec: made in the standing it needs through
 * POST /api/testing/projects, changed through the API the project menu uses, and read as the
 * lists read them. Every list also holds the seed's projects and those earlier specs of the
 * worker made; a draft made with a session (`makeDraft`) answers its folder in the store's tree as
 * well, where its definition chat's session runs. A project made with a session has items placed
 * on its timeline as Pilot places them, and saves of them as Pilot's (POST /api/testing/projects/<id>/items and
 * /api/testing/items/<id>/saves), its handbook and its project document saved
 * (/api/testing/projects/<id>/{handbook,draft}/saves), its session's turn ended, a document it settled whole marked
 * Done by Pilot and files it copied attached to an item (/api/testing/items/<id>/attachments); they
 * are answered through the items API, and a block of the handbook or of the project document by its
 * path in the store's tree, as the record answers it (/api/testing/sync/answer). A work item is placed by repository and its session started
 * in an environment of Pilot's own its start takes or creates in the worker's fake controller
 * (/api/testing/projects/<id>/work; `controller.ts` drives the fake), and read as the timeline and
 * the session log read it; a file its session wrote in that environment is registered as its
 * worker's `register_document` registers it (/api/testing/items/<id>/registrations), and a file or
 * a folder attached as its `attach_file` attaches it (/api/testing/items/<id>/worker-attachments),
 * each the effect of the call a tool-use id names; a registered document's writer is asked about
 * its blocks as the pre-ruling pass's `ask_writer` asks (/api/testing/items/<id>/writer-questions).
 */

import { expect, type Page } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';
import { makeUnique } from './helpers';

type ProjectSpec = components['schemas']['InventedProjectCreateSchema.6d6b324'];
type Invented = components['schemas']['InventedProjectSchema.6d6b324'];
type ProjectTab = components['schemas']['ProjectListResponseSchema.e86ccd6.ProjectTabSchema'];
type ProjectHead = components['schemas']['ProjectHeadSchema.e86ccd6'];
type TransitionKind = components['schemas']['TransitionRequestSchema.e86ccd6']['kind'];
type ItemSpec = components['schemas']['InventedItemCreateSchema.6d6b324'];
type Save = components['schemas']['InventedSaveSchema.6d6b324'];
type InventedFile = components['schemas']['InventedAttachmentsCreateSchema.6d6b324.InventedFileSchema'];
/** A file to attach, its bytes as they are. */
export type AttachedFile = Omit<InventedFile, 'content'> & { content: string | Buffer };
type WorkSpec = components['schemas']['InventedWorkCreateSchema.6d6b324'];
type WriterQuestion = components['schemas']['InventedWriterQuestionsCreateSchema.6d6b324.InventedWriterQuestionSchema'];
type Timeline = components['schemas']['TimelineSchema.1fdd8ae'];
type TimelineItem = Timeline['items'][number];
type Work = NonNullable<TimelineItem['work']>;
type Environment = NonNullable<Work['environment']>;
type RecordPage = components['schemas']['SessionRecordPageSchema.01118bb'];
type Block = components['schemas']['TimelineSchema.1fdd8ae.BlockSchema'];
type BlockPart = components['schemas']['TimelineSchema.1fdd8ae.BlockPartSchema'];

/** The slug the testing route gives an open project it makes: `project-` and its id's first 12 hex digits. */
export function slugOf(projectId: string): string {
  return `project-${projectId.replaceAll('-', '').slice(0, 12)}`;
}

export class Projects {
  /**
   * The repository the spec's work items are placed by: its own, so that a start takes no
   * environment of Pilot's that an earlier spec of the worker left free.
   */
  readonly repo = `example/${makeUnique('Example')}`;

  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
  ) {}

  /** A project in the standing given; answers its id. */
  async make(spec: ProjectSpec): Promise<string> {
    return (await this.invent(spec)).id;
  }

  /** A project whose session, in an environment of its own, places its items; answers its id. */
  async makeWithSession(spec: Omit<ProjectSpec, 'environment_id'>): Promise<string> {
    return this.make({ ...spec, environment_id: await this.sessionEnvironment() });
  }

  /**
   * A draft whose session, in an environment of its own, saves its project document; answers its id
   * and its folder in the store's tree, `draft-<number>`, where its definition chat's session runs.
   */
  async makeDraft(spec: Omit<ProjectSpec, 'state' | 'environment_id'>): Promise<Invented> {
    return this.invent({ ...spec, state: 'draft', environment_id: await this.sessionEnvironment() });
  }

  private async invent(spec: ProjectSpec): Promise<Invented> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/projects`, { data: spec });
    expect(response.status(), await response.text()).toBe(201);
    return (await response.json()) as Invented;
  }

  /** An environment of its own for a project's session; answers its id. */
  private async sessionEnvironment(): Promise<string> {
    const environment = makeUnique('env');
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/environments`, {
      data: { id: environment, name: environment },
    });
    expect(response.status(), await response.text()).toBe(201);
    return environment;
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

  /** A save of the project's handbook, or of its project document (`draft`), by the project's session. */
  async saveProjectDocument(projectId: string, role: 'handbook' | 'draft', text: string): Promise<Save> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/projects/${projectId}/${role}/saves`, {
      data: { text },
    });
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as Save;
  }

  /** The project's session's turn ends, as the relay ends it: no text is being written, and a change is an edit. */
  async endTurn(projectId: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/projects/${projectId}/turn-ends`);
    expect(response.status(), await response.text()).toBe(204);
  }

  /** Files the project's session attaches to an item in one call, one batch; answers their ids, in the files' order. */
  async attach(itemId: string, files: AttachedFile[]): Promise<string[]> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/items/${itemId}/attachments`, {
      data: { files: files.map((file) => ({ ...file, content: Buffer.from(file.content).toString('base64') })) },
    });
    expect(response.status(), await response.text()).toBe(201);
    return ((await response.json()) as { ids: string[] }).ids;
  }

  /** Pilot marks Done a document whose every block it answered or deferred. */
  async doneByPilot(itemId: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/items/${itemId}/done`);
    expect(response.status(), await response.text()).toBe(204);
  }

  /** A person's answer to a block of the open project's handbook, or of its project document (`draft`). */
  async answerProjectDocument(projectId: string, role: 'handbook' | 'draft', block: string, answer: string, handle: string): Promise<void> {
    const path = `${slugOf(projectId)}/${role === 'handbook' ? 'handbook.md' : 'project.md'}`;
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/sync/answer`, {
      data: { path, block, answer, user: handle },
    });
    expect(response.status(), await response.text()).toBe(200);
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

  /** The signed-in person marks a review Reviewed. */
  async reviewed(itemId: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/items/${itemId}/reviewed`);
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

  /**
   * A work item placed on the project's timeline by the spec's repository, its session started as
   * Pilot starts one, through the gate, once the request commits, in an environment its start takes
   * or creates; answers its id, its session's.
   */
  async startWork(projectId: string, spec: Omit<WorkSpec, 'repo'>): Promise<string> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/projects/${projectId}/work`, {
      data: { ...spec, repo: this.repo },
    });
    expect(response.status(), await response.text()).toBe(201);
    return ((await response.json()) as { id: string }).id;
  }

  /**
   * The document a work item's session wrote at `path` in its environment, registered as its worker
   * registers it: read and parsed now, read again once the turn that ends its run commits; minted
   * while the session's turn is in flight, the effect of the call `toolUseId` names, or of none.
   * Answers its id.
   */
  async register(workId: string, path: string, toolUseId?: string): Promise<string> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/items/${workId}/registrations`, {
      data: { path, tool_use_id: toolUseId },
    });
    expect(response.status(), await response.text()).toBe(201);
    return ((await response.json()) as { id: string }).id;
  }

  /**
   * The file or the folder a work item's session wrote at `path` in its environment, attached as its
   * worker attaches it, on the item `to` names, else on the work item; while the session's turn is in
   * flight, the effect of the call `toolUseId` names, or of none. Answers the attachments' ids.
   */
  async workerAttach(workId: string, path: string, { to, toolUseId }: { to?: string; toolUseId?: string } = {}): Promise<string[]> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/items/${workId}/worker-attachments`, {
      data: { path, to, tool_use_id: toolUseId },
    });
    expect(response.status(), await response.text()).toBe(201);
    return ((await response.json()) as { ids: string[] }).ids;
  }

  /** A registered document's writer asked about its blocks, by their local ids, as the pre-ruling pass asks. */
  async askWriter(documentId: string, questions: WriterQuestion[]): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/items/${documentId}/writer-questions`, {
      data: { questions },
    });
    expect(response.status(), await response.text()).toBe(201);
  }

  /** The environment a work item's start took or created, once it has one, as its row stands. */
  async environment(projectId: string, itemId: string): Promise<Environment> {
    await expect.poll(async () => (await this.work(projectId, itemId)).environment).not.toBeNull();
    return (await this.work(projectId, itemId)).environment!;
  }

  /** An item, as the signed-in person reads the project's timeline. */
  async item(projectId: string, itemId: string): Promise<TimelineItem> {
    return (await this.timeline(projectId)).items.find((each) => each.id === itemId)!;
  }

  /** A work item's session, as the signed-in person reads the project's timeline. */
  async work(projectId: string, itemId: string): Promise<Work> {
    return (await this.item(projectId, itemId)).work!;
  }

  /** Stops a work item's session, as the signed-in person: answers its status. */
  async stop(sessionId: string): Promise<Work> {
    const response = await this.page.request.post(`${this.backendUrl}/api/sessions/${sessionId}/stop`);
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as Work;
  }

  /** Resumes a stopped or failed work item's session: answers its status. */
  async resume(sessionId: string): Promise<Work> {
    const response = await this.page.request.post(`${this.backendUrl}/api/sessions/${sessionId}/resume`);
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as Work;
  }

  /** A work item's session's records after record `after`, as the session log reads them. */
  async records(sessionId: string, after = 0): Promise<RecordPage> {
    const response = await this.page.request.get(`${this.backendUrl}/api/sessions/${sessionId}/records?after=${after}`);
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as RecordPage;
  }

  /** A one-ask item's block, as the signed-in person reads the project's timeline. */
  async block(projectId: string, itemId: string): Promise<Block> {
    const item = await this.item(projectId, itemId);
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

/**
 * A project's chats for a spec (F38, F40). The suite's backends start every chat's session in the
 * store environment of their fake controller (backend-env-extensions.ts), which `ready()` adds once
 * per backend, running and exempt, its tree holding the store repo, every chat session's cwd, and
 * the project's folder, which the fake requires of a boxed create (TD §4.2). A message is sent as a
 * person sends it (POST /api/projects/<id>/chat/messages): by the signed-in person, or by another
 * person on a connection of their own (`other()`); or through the composer, after `opening()`. A
 * chat's start creates its headless session in the store, `claude-<n>` in the order the backend
 * creates them there; `start()` and `opening()` name it, and the spec plays its turns through
 * `controller` once it is working. While a turn is in flight, `answer()` records a person's answer
 * to a block as the chat's brain records it (POST /api/testing/projects/<id>/chat/answers), the
 * place *In the chat* goes to.
 */

import { randomUUID } from 'node:crypto';
import { expect, type APIRequestContext, type Page, type PlaywrightWorkerArgs } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';
import { FAKE_CONTROLLER_TOKEN, STORE_ENVIRONMENT } from './backend-env-extensions';
import type { Controller } from './controller';
import { slugOf } from './projects';

type Sent = components['schemas']['ChatTurnSchema.f9d9b43'];
type ChatList = components['schemas']['ChatListSchema.f9d9b43'];

/** The store repo's root, every chat session's cwd (backend/app/services/session_scope.py). */
const STORE_REPO = '/work/PilotProjects';
/** The store's tree, a folder per project under it. */
const PROJECTS = '/work/Projects';

/** A chat a message opened, and its session's name in the store. */
interface Started {
  chat: string;
  session: string;
}

/** Another person, signed in with a handle on a connection of their own. */
class OtherPerson {
  private constructor(
    private readonly request: APIRequestContext,
    readonly handle: string,
  ) {}

  static async signIn(playwright: PlaywrightWorkerArgs['playwright'], backendUrl: string, name: string, handle: string): Promise<OtherPerson> {
    const request = await playwright.request.newContext({ baseURL: backendUrl });
    const session = await request.post('/api/testing/auth/session', { data: { subject: `other-${randomUUID()}`, name, roles: ['editor'] } });
    expect(session.ok(), await session.text()).toBe(true);
    const chosen = await request.post('/api/people/self/handle', { data: { handle } });
    expect(chosen.status(), await chosen.text()).toBe(201);
    return new OtherPerson(request, handle);
  }

  /** A message of theirs to the project's chat. */
  async send(projectId: string, words: string): Promise<Sent> {
    const response = await this.request.post(`/api/projects/${projectId}/chat/messages`, { data: { words } });
    expect(response.status(), await response.text()).toBe(201);
    return (await response.json()) as Sent;
  }

  async dispose(): Promise<void> {
    await this.request.dispose();
  }
}

export class Chats {
  /** The store's environment in the fake, where every chat's session runs. */
  readonly store = STORE_ENVIRONMENT;
  private readonly others: OtherPerson[] = [];

  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
    private readonly controller: Controller,
    private readonly playwright: PlaywrightWorkerArgs['playwright'],
  ) {}

  /** The store in the fake, its tree holding the store repo and the project's folder, an open project's by its slug unless named. */
  async ready(projectId: string, folder = slugOf(projectId)): Promise<void> {
    const response = await this.page.request.get(`${this.backendUrl}/api/testing/controller/environments/${this.store}`, {
      headers: { Authorization: `Bearer ${FAKE_CONTROLLER_TOKEN}` },
    });
    expect([200, 404], await response.text()).toContain(response.status());
    if (response.status() === 404) {
      await this.controller.addEnvironment(this.store, 'example/PilotProjects', { exempt: true });
      await this.controller.putFile(this.store, `${STORE_REPO}/CLAUDE.md`, '# The store\n');
    }
    await this.controller.putFile(this.store, `${PROJECTS}/${folder}/project.md`, '# Invented\n');
  }

  /** A message of the signed-in person's to the project's chat. */
  async send(projectId: string, words: string): Promise<Sent> {
    const response = await this.page.request.post(`${this.backendUrl}/api/projects/${projectId}/chat/messages`, { data: { words } });
    expect(response.status(), await response.text()).toBe(201);
    return (await response.json()) as Sent;
  }

  /**
   * The message that opens a chat, the signed-in person's or `by`'s: answers the chat and its
   * session's name in the store, once the session works on its first turn.
   */
  async start(projectId: string, words: string, by?: OtherPerson): Promise<Started> {
    const opened = await this.opening(projectId);
    const sent = await (by === undefined ? this.send(projectId, words) : by.send(projectId, words));
    return { chat: sent.chat, session: await opened() };
  }

  /**
   * The store, ready for the project's chat — a draft's in its `folder` (`Projects.makeDraft`) — and a
   * wait for the session the next message opens there, sent through the API or the composer: answers
   * its name once it works on its first turn.
   */
  async opening(projectId: string, folder?: string): Promise<() => Promise<string>> {
    await this.ready(projectId, folder);
    const before = new Set(await this.controller.sessions(this.store));
    return async () => {
      let session = '';
      await expect
        .poll(async () => {
          session = (await this.controller.sessions(this.store)).find((name) => !before.has(name)) ?? '';
          return session;
        })
        .not.toBe('');
      await this.working(session);
      return session;
    };
  }

  /** Returns once the store's session works on a turn: the message sent to it. */
  async working(session: string): Promise<void> {
    await expect.poll(async () => (await this.controller.sessionViews(this.store)).find((each) => each.name === session)?.working).toBe(true);
  }

  /**
   * `person`'s answer to the block `<item>/<local id>`, recorded through the project's open chat as
   * its brain's `answer` records it while its turn is in flight (F42.1): the effect of the call
   * `toolUseId` names.
   */
  async answer(
    projectId: string,
    block: string,
    value: string,
    person: string,
    { note, toolUseId }: { note?: string; toolUseId?: string } = {},
  ): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/testing/projects/${projectId}/chat/answers`, {
      data: { block, value, for: person, note, tool_use_id: toolUseId },
    });
    expect(response.status(), await response.text()).toBe(201);
  }

  /** Returns once Pilot no longer answers in the project's latest chat: its next message is taken. */
  async idle(projectId: string): Promise<void> {
    await expect.poll(async () => (await this.list(projectId)).chats.at(-1)?.answering).toBe(false);
  }

  /** The signed-in person stops Pilot's answer in the project's open chat (F44). */
  async stop(projectId: string): Promise<void> {
    const response = await this.page.request.post(`${this.backendUrl}/api/projects/${projectId}/chat/stop`);
    expect(response.status(), await response.text()).toBe(200);
  }

  /** The signed-in person has seen the project's chat to its end (F43). */
  async seen(projectId: string): Promise<void> {
    const response = await this.page.request.put(`${this.backendUrl}/api/projects/${projectId}/chat/read`);
    expect(response.status(), await response.text()).toBe(200);
  }

  /** The project's chats, as the signed-in person reads them. */
  async list(projectId: string): Promise<ChatList> {
    const response = await this.page.request.get(`${this.backendUrl}/api/projects/${projectId}/chats`);
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as ChatList;
  }

  /** Another person, a member or not, signed in on a connection of their own. */
  async other(name: string, handle: string): Promise<OtherPerson> {
    const person = await OtherPerson.signIn(this.playwright, this.backendUrl, name, handle);
    this.others.push(person);
    return person;
  }

  async dispose(): Promise<void> {
    await Promise.all(this.others.map((person) => person.dispose()));
  }
}

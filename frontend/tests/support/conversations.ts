/**
 * A project's conversations for a spec (F150.10, F150.12): a session outside Pilot talking to
 * Pilot about a project through the routes its projects surface calls. `caller()` is such a
 * session: a service user of its own, signed in on a connection of its own, calling from an
 * environment the record names, as the session it names. It opens a conversation as the surface
 * does (POST /api/conversations), sends its next message and ends it. A conversation's session
 * runs in the store's fake environment as a chat's does (chats.ts): `start()` answers its name
 * there once it works on its first turn, and the spec plays its turns through `controller`.
 * `list()` and `stop()` are the signed-in person's read of the project's conversations and their
 * Stop of Pilot's answer in one.
 */

import { randomUUID } from 'node:crypto';
import { expect, type APIRequestContext, type Page, type PlaywrightWorkerArgs } from '@playwright/test';
import type { components } from '@/lib/api/generated/types';
import type { Chats } from './chats';
import { makeUniqueToken } from './helpers';

type Conversation = components['schemas']['ConversationSchema.38a7d5c'];
type ConversationList = components['schemas']['ProjectConversationListSchema.de6f08c'];

/** A conversation a caller opened, and its session's name in the store. */
interface Started {
  conversation: string;
  session: string;
}

/** A session outside Pilot, calling as a service user from its environment. */
class Caller {
  constructor(
    private readonly request: APIRequestContext,
    private readonly chats: Chats,
  ) {}

  /** Opens a conversation on the project with `words`: answers it and its session's name in the store, once that works on its first turn. */
  async start(projectId: string, words: string): Promise<Started> {
    const opened = await this.chats.opening(projectId);
    const response = await this.request.post('/api/conversations', { data: { address: projectId, words } });
    expect(response.status(), await response.text()).toBe(201);
    const conversation = (await response.json()) as Conversation;
    return { conversation: conversation.id, session: await opened() };
  }

  /** Its next message in the conversation. */
  async send(conversationId: string, words: string): Promise<void> {
    const response = await this.request.post(`/api/conversations/${conversationId}/messages`, { data: { words } });
    expect(response.status(), await response.text()).toBe(201);
  }

  /** Ends the conversation. */
  async end(conversationId: string): Promise<void> {
    const response = await this.request.post(`/api/conversations/${conversationId}/end`);
    expect(response.status(), await response.text()).toBe(200);
  }

  async dispose(): Promise<void> {
    await this.request.dispose();
  }
}

export class Conversations {
  private readonly callers: Caller[] = [];

  constructor(
    private readonly page: Page,
    private readonly backendUrl: string,
    private readonly chats: Chats,
    private readonly playwright: PlaywrightWorkerArgs['playwright'],
  ) {}

  /**
   * A session calling from the environment `name`, which the record gets under an id of its own,
   * as the session `session`, or as one that names none; answers the caller and its environment's id.
   */
  async caller(name: string, session?: string): Promise<{ caller: Caller; environment: string }> {
    const token = makeUniqueToken(6);
    const environment = `example-${name.toLowerCase()}-${token}`;
    const placed = await this.page.request.post(`${this.backendUrl}/api/testing/environments`, { data: { id: environment, name } });
    expect(placed.status(), await placed.text()).toBe(201);
    const subject = `service-${randomUUID()}`;
    const made = await this.page.request.post(`${this.backendUrl}/api/testing/service-users`, {
      data: { handle: `fleet-${token}`, name: 'KubeCoder fleet', subject },
    });
    expect(made.status(), await made.text()).toBe(201);
    const request = await this.playwright.request.newContext({
      baseURL: this.backendUrl,
      extraHTTPHeaders: { 'X-Pilot-Environment': environment, ...(session === undefined ? {} : { 'X-Pilot-Session': session }) },
    });
    const signedIn = await request.post('/api/testing/auth/session', { data: { subject, name: 'KubeCoder fleet', roles: ['editor'] } });
    expect(signedIn.ok(), await signedIn.text()).toBe(true);
    const caller = new Caller(request, this.chats);
    this.callers.push(caller);
    return { caller, environment };
  }

  /** The project's conversations, as the signed-in person reads them. */
  async list(projectId: string): Promise<ConversationList> {
    const response = await this.page.request.get(`${this.backendUrl}/api/projects/${projectId}/conversations`);
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as ConversationList;
  }

  /** Returns once Pilot no longer answers in the conversation. */
  async idle(projectId: string, conversationId: string): Promise<void> {
    await expect.poll(async () => (await this.list(projectId)).conversations.find((each) => each.id === conversationId)?.answering).toBe(false);
  }

  async dispose(): Promise<void> {
    await Promise.all(this.callers.map((caller) => caller.dispose()));
  }
}
